import datetime as dt,json,re,urllib.parse,os
from dataclasses import dataclass,field
from qgis.core import QgsCoordinateReferenceSystem,QgsProcessingException
from .network import get
ENDPOINT='https://data.geopf.fr/wfs/ows';TYPENAME='IGNF_LIDAR-HD_METADONNEE:metadata'
@dataclass
class Record:
    id:str;url:str;edition:str;planimetric:str;altimetric:str;tile_key:str;resource_date:str=None;points:int=None;warnings:list=field(default_factory=list)
    def audit(self):return {'id':self.id,'url_npl':self.url,'catalogue_edition':self.edition,'resource_date':self.resource_date,'tile_key':self.tile_key,'systeme_planimetrique':self.planimetric,'systeme_altimetrique':self.altimetric,'nombre_points':self.points,'warnings':self.warnings}
def normalize_date(value,warnings):
    raw=str(value or '').strip()
    if not raw:return 'sans_date'
    candidate=raw[:-1] if raw.endswith('Z') else raw;candidate=candidate.split('T',1)[0].split(' ',1)[0]
    try:
        value=dt.date.fromisoformat(candidate).isoformat()
        if value!=raw:warnings.append(f"date_edition normalisée de '{raw}' vers '{value}'")
        return value
    except ValueError:warnings.append(f"date_edition non standard conservée : '{raw}'");return re.sub(r'[^0-9A-Za-z_-]','_',raw)
def resource_date(url):
    matches=re.findall(r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)',url or '')
    return matches[-1] if matches else None
def tile_key(props,url,feature_id):
    key=str(props.get('coordonnees_NW') or '').strip()
    if key:return key
    name=os.path.basename(urllib.parse.urlparse(url).path)
    match=re.search(r'(?:FXX|GLP|MTQ|REU|MYT)[_-]?(\d{4})[_-](\d{4})',name,re.I)
    if match:return match.group(1)+'-'+match.group(2)
    match=re.search(r'_(\d{4})_(\d{4})_',name)
    return match.group(1)+'-'+match.group(2) if match else feature_id
def parse(data):
    records=[];rejects=[];warnings=[]
    for index,feature in enumerate(data.get('features',[])):
        props=feature.get('properties') or {};url=props.get('url_npl') or props.get('URL_NPL');fid=str(feature.get('id') or f'features[{index}]')
        if feature.get('type')!='Feature' or not url:rejects.append(f'features[{index}] : Feature/url_npl manquant');continue
        local=[];edition=normalize_date(props.get('date_edition'),local);rdate=resource_date(str(url));key=tile_key(props,str(url),fid);points=props.get('nombre_points')
        try:points=int(points) if points not in (None,'') else None
        except (TypeError,ValueError):local.append('nombre_points invalide, ignoré');points=None
        if rdate and rdate!=edition:local.append(f"catalogue {edition} → ressource {rdate}")
        record=Record(fid,str(url),edition,str(props.get('systeme_planimetrique') or '').strip(),str(props.get('systeme_altimetrique') or '').strip(),key,rdate,points,local)
        records.append(record);warnings.extend(record.id+' : '+x for x in local)
    return records,rejects,warnings
def query_records(extent,crs,feedback):
    bbox=f'{extent.xMinimum()},{extent.yMinimum()},{extent.xMaximum()},{extent.yMaximum()},{crs.authid()}'
    params={'SERVICE':'WFS','VERSION':'2.0.0','REQUEST':'GetFeature','TYPENAMES':TYPENAME,'OUTPUTFORMAT':'application/json','BBOX':bbox};url=ENDPOINT+'?'+urllib.parse.urlencode(params,safe=':,');feedback.pushInfo('Requête WFS : '+url)
    return (*parse(json.loads(get(url,'application/json',feedback).decode('utf-8'))),url)
def grouped(records):
    result={}
    for record in records:result.setdefault(record.edition,[]).append(record)
    return dict(sorted(result.items(),reverse=True))
def latest_coverage(records):
    by_tile={}
    for record in records:
        current=by_tile.get(record.tile_key)
        if current is None or (record.edition,record.id)>(current.edition,current.id):by_tile[record.tile_key]=record
    return sorted(by_tile.values(),key=lambda r:r.tile_key)
def build_jobs(records,mode,selection):
    groups=grouped(records);editions=list(groups)
    if mode==0:return [(edition,groups[edition],'catalogue_edition') for edition in editions]
    if mode==1:
        latest=latest_coverage(records)
        return [('couverture_plus_recente',latest,'latest_per_tile')]
    requested=[x.strip() for x in re.split(r'[,;\n]+',selection or '') if x.strip()]
    missing=[x for x in requested if x not in groups]
    if missing:raise QgsProcessingException('Édition(s) absente(s) : '+', '.join(missing)+'. Disponibles : '+', '.join(editions))
    if not requested:raise QgsProcessingException('Saisir au moins une édition.')
    return [(edition,groups[edition],'catalogue_edition') for edition in requested]
ALIASES={'LAMB93':'EPSG:2154','LAMBERT93':'EPSG:2154','LAMBERT-93':'EPSG:2154','RGF93/LAMB93':'EPSG:2154'}
def resolve_crs(value):
    token=re.sub(r'\s+','',str(value or '').upper());auth=ALIASES.get(token)
    if not auth:
        match=re.search(r'EPSG(?::|=|_)?(\d+)',token);auth='EPSG:'+match.group(1) if match else None
    crs=QgsCoordinateReferenceSystem(auth or '')
    if not crs.isValid():raise QgsProcessingException('Système planimétrique non résolu : '+repr(value))
    return crs,'mapping '+token+' → '+auth
