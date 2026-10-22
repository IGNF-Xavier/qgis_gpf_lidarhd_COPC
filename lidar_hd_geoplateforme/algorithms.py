import json,os,re,shutil,time
from qgis.core import *
from .render import apply_default_renderer
from .core import query_records,grouped,build_jobs,resolve_crs
from .network import probe_url
from .process_utils import run_pipeline,run_command_timeout
from .proxy_env import build_pdal_environment
from .pdal_support import chunk_url,url_sets,attempt_plan,pipeline_stages,bounds_string,classify_pdal_log,key_network_lines
class Base(QgsProcessingAlgorithm):
    E='EXTENT';C='CRS';D='OUT_DIR'
    def group(self):return 'Éditions LiDAR HD'
    def groupId(self):return 'editions'
    def add_extent(self):
        self.addParameter(QgsProcessingParameterExtent(self.E,'Emprise'));self.addParameter(QgsProcessingParameterCrs(self.C,'SCR de repli',optional=True))
    def crs(self,p,c):
        x=self.parameterAsExtentCrs(p,self.E,c) if hasattr(self,'parameterAsExtentCrs') else QgsCoordinateReferenceSystem()
        if x.isValid():return x
        x=self.parameterAsCrs(p,self.C,c);return x if x.isValid() else c.project().crs()
    def output_folder(self,p,c,f):
        raw=self.parameterAsString(p,self.D,c)
        is_generated_out_dir=(str(raw).upper()=='TEMPORARY_OUTPUT' or (os.path.basename(str(raw)).upper()=='OUT_DIR' and os.path.basename(os.path.dirname(str(raw))).lower().startswith('processing_')))
        folder=c.temporaryFolder() if not raw or is_generated_out_dir else raw
        folder=os.path.abspath(os.path.normpath(folder))
        if folder.lower().startswith(('http://','https://')):
            raise QgsProcessingException('Le dossier de sortie doit être local, pas une URL : '+folder)
        os.makedirs(folder,exist_ok=True)
        f.pushInfo('Dossier local absolu de sortie : '+folder)
        return folder
    def inventory(self,p,c,f):
        extent=self.parameterAsExtent(p,self.E,c);crs=self.crs(p,c);records,rejects,warnings,url=query_records(extent,crs,f)
        for warn in warnings:
            if hasattr(f,'pushWarning'):f.pushWarning(warn)
            else:f.pushInfo('AVERTISSEMENT : '+warn)
        for reject in rejects:f.reportError(reject,False)
        return extent,crs,records,grouped(records),url
class ListEditionsAlgorithm(Base):
    O='INVENTORY'
    def name(self):return 'list_editions'
    def displayName(self):return '1. Lister les éditions disponibles'
    def createInstance(self):return ListEditionsAlgorithm()
    def shortHelpString(self):
        return """<h2>Lister les éditions LiDAR HD</h2><p>Interroge <b>IGNF_LIDAR-HD_METADONNEE:metadata</b> sur l'emprise et crée un inventaire JSON local des dates, sources COPC et points déclarés.</p>"""
    def initAlgorithm(self,config=None):self.add_extent();self.addParameter(QgsProcessingParameterFileDestination(self.O,'Inventaire JSON','JSON (*.json)'))
    def processAlgorithm(self,p,c,f):
        f.setProgress(10);extent,crs,records,groups,url=self.inventory(p,c,f);path=self.parameterAsFileOutput(p,self.O,c)
        data={'wfs_request':url,'crs_emprise':crs.authid(),'editions':[{'edition':edition,'fichiers':len(records),'points_declares':sum(r.points or 0 for r in records)} for edition,records in groups.items()]}
        with open(path,'w',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
        for item in data['editions']:f.pushInfo(f"Édition {item['edition']} : {item['fichiers']} COPC, {item['points_declares']} points déclarés")
        f.setProgress(100);return {self.O:path}
class ExtractEditionsAlgorithm(Base):
    MODE='EDITION_MODE';SEL='EDITIONS';PREFIX='PREFIX';R='RESOLUTION';URL_MODE='URL_MODE';DIAG='DIAGNOSTIC';STALL='STALL_SECONDS';L='LOAD';M='MANIFEST';OUT='OUTPUT_FOLDER'
    def name(self):return 'extract_editions'
    def displayName(self):return '2. Extraire un COPC par édition'
    def createInstance(self):return ExtractEditionsAlgorithm()
    def shortHelpString(self):
        return """<h2>Extraire un COPC par édition LiDAR HD</h2>
<p>Lit à distance les COPC référencés par <b>IGNF_LIDAR-HD_METADONNEE:metadata</b>, limite les points à l'emprise puis écrit un <b>COPC local</b>.</p>
<h3>Emprise et SCR</h3><p>Le SCR est détecté depuis l'emprise, le paramètre de repli ou le projet, puis l'emprise est reprojetée dans le SCR de chaque source.</p>
<h3>Éditions</h3><ul><li><b>Toutes</b> : un COPC par date catalogue.</li><li><b>Plus récente</b> : métadonnée catalogue la plus récente par dalle.</li><li><b>Sélectionnées</b> : dates AAAA-MM-JJ séparées par « ; ».</li></ul><p>Le journal distingue date catalogue et date présente dans l'URL de ressource.</p>
<h3>Résolution</h3><ul><li><b>0 m</b> : native, production complète et lourde.</li><li><b>0,25 m</b> : très détaillée.</li><li><b>0,50 m</b> : compromis recommandé dans QGIS.</li><li><b>1 m</b> : exploration rapide/grande emprise.</li><li><b>2 m et plus</b> : aperçu.</li></ul><p>Ce paramètre règle le niveau de détail de <code>readers.copc</code>, pas un pixel raster.</p>
<h3>Accès aux COPC</h3><p>Automatique utilise en priorité l'URL <b>chunk</b> (<code>/chunk/telechargement/…</code>, recommandée par le tutoriel) puis, en repli, l'URL WFS originale (une seconde pipeline est reconstruite). Le précontrôle obligatoire vérifie deux requêtes HTTP Range, Content-Range et la signature LASF avant toute pipeline longue.</p>
<h3>Réseau et certificats de PDAL</h3><p>PDAL s'exécute dans un processus séparé qui n'utilise pas la pile réseau de QGIS. Le plugin lui transmet le proxy résolu par QGIS (y compris via un fichier PAC) ainsi qu'un bundle de certificats (<code>ARBITER_CA_INFO</code>). Sans ce bundle, PDAL échoue en TLS puis réessaie lentement (« Could not read from »).</p><h3>Suivi</h3><p>Un message toutes les 15 s. « Fichier de sortie non encore créé » est normal pendant l'ouverture distante et n'indique pas un blocage.</p><h3>Diagnostic individuel</h3><p>Décoché par défaut. Ajoute un test rapide <code>pdal info --metadata</code>. Un timeout rapide reste indéterminé et peut être validé par l'extraction réelle.</p>
<h3>Seuil sans croissance</h3><p>Actif seulement après création du fichier local. Avant cela, PDAL peut être en phase d'ouverture distante.</p>
<h3>Sorties locales</h3><p><code>TEMPORARY_OUTPUT</code> est résolu vers le dossier temporaire local QGIS. Les chemins absolus du COPC et de la pipeline sont journalisés.</p>
<h3>Mode strict</h3><p>Une source indispensable incompatible ou une extraction réelle en échec arrête la production. Aucun COPC incomplet n'est produit silencieusement.</p>"""
    def initAlgorithm(self,config=None):
        self.add_extent();self.addParameter(QgsProcessingParameterEnum(self.MODE,'Éditions à produire',['Toutes les éditions','Édition la plus récente','Éditions sélectionnées'],defaultValue=1));self.addParameter(QgsProcessingParameterString(self.SEL,'Éditions sélectionnées (AAAA-MM-JJ, séparées par ;)',optional=True));self.addParameter(QgsProcessingParameterFolderDestination(self.D,'Dossier de destination'));self.addParameter(QgsProcessingParameterString(self.PREFIX,'Préfixe des fichiers',defaultValue='lidar_hd'));self.addParameter(QgsProcessingParameterNumber(self.R,'Résolution (0=native)',QgsProcessingParameterNumber.Double,0,False,0));self.addParameter(QgsProcessingParameterEnum(self.URL_MODE,'Accès aux COPC',['Automatique : chunk (recommandé) puis URL WFS en repli','URL WFS originale uniquement','URL chunk uniquement'],defaultValue=0));self.addParameter(QgsProcessingParameterBoolean(self.DIAG,'Diagnostiquer chaque source avant la fusion',False));self.addParameter(QgsProcessingParameterNumber(self.STALL,'Arrêter une source sans croissance après (secondes, 0=désactivé)',QgsProcessingParameterNumber.Integer,120,False,0,3600));self.addParameter(QgsProcessingParameterBoolean(self.L,'Charger les COPC produits dans QGIS',True));self.addOutput(QgsProcessingOutputFile(self.M,'Manifeste JSON'));self.addOutput(QgsProcessingOutputFile(self.OUT,'Dossier de sortie'))
    @staticmethod
    def _chunk_url(url):
        return chunk_url(url)
    def _url_sets(self, records, mode):
        # Conforme au tutoriel : chunk en priorité, URL WFS originale en véritable repli.
        return url_sets([record.url for record in records],mode)
    def _build_pipeline(self, records, urls, extent, source, context, resolution, output, pipeline, edition, wfs_url, selection_method):
        output=os.path.abspath(output);pipeline=os.path.abspath(pipeline)
        if output.lower().startswith(('http://','https://')) or not os.path.isabs(output):
            raise QgsProcessingException('Le writers.copc exige un chemin local absolu : '+output)
        readers=[];audit=[]
        for record,url in zip(records,urls):
            crs,note=resolve_crs(record.planimetric);tc=context.project().transformContext();tile_extent=extent if source==crs else QgsCoordinateTransform(source,crs,tc).transformBoundingBox(extent)
            readers.append((url,bounds_string(tile_extent.xMinimum(),tile_extent.xMaximum(),tile_extent.yMinimum(),tile_extent.yMaximum())))
            item=record.audit();item.update({'crs':crs.authid(),'crs_source':note,'effective_url':url,'selection_method':selection_method});audit.append(item)
        stages=pipeline_stages(readers,output,resolution)
        with open(pipeline,'w',encoding='utf-8') as stream:json.dump({'pipeline':stages,'metadata':{'production':edition,'selection_method':selection_method,'wfs_request':wfs_url,'sources':audit}},stream,ensure_ascii=False,indent=2)
    def _select_effective_urls(self,records,url_mode,feedback):
        strategies=self._url_sets(records,url_mode);selected=[];checks=[]
        feedback.pushInfo(f'Précontrôle HTTP Range obligatoire de {len(records)} source(s)')
        for index,record in enumerate(records,1):
            item={'id':record.id,'tile_key':record.tile_key,'attempts':[],'selected_strategy':None,'selected_url':None}
            for strategy,urls in strategies:
                url=urls[index-1];feedback.pushInfo(f'Précontrôle {index}/{len(records)} — {record.id} — {strategy}')
                result=probe_url(url,feedback);item['attempts'].append({'strategy':strategy,'url':url,'http':result})
                for check in result['ranges']:
                    feedback.pushInfo(f"  {check['range']} : HTTP {check['status']}, Content-Range={check['content_range'] or 'absent'}, octets={check['bytes_received']}, LASF={check.get('lasf_signature')}, compatible={check['compatible']}")
                if result['range_compatible']:
                    item['selected_strategy']=strategy;item['selected_url']=url;selected.append(url);feedback.pushInfo(f'  URL retenue : {strategy}');break
            checks.append(item)
            if not item['selected_url']:
                feedback.reportError('=== SOURCE INCOMPATIBLE AVEC LA LECTURE COPC DISTANTE — MODE STRICT ===',False)
                feedback.reportError(f'Dalle : {record.tile_key}; métadonnée : {record.id}; catalogue : {record.edition}; ressource : {record.resource_date or "non datée"}',False)
                feedback.reportError('Aucune URL ne fournit deux réponses HTTP 206 avec Content-Range conforme et signature LASF. Aucun COPC incomplet ne sera produit.',False)
                raise QgsProcessingException(f'Lecture COPC distante impossible pour la dalle {record.tile_key} ({record.id}) : accès HTTP Range incompatible ou ressource non LAS/COPC.')
        feedback.pushInfo(f'Précontrôle terminé : {len(selected)}/{len(records)} source(s) compatibles.')
        return selected,checks
    def _diagnose_sources(self,pdal,records,extent,source,context,resolution,folder,prefix,edition,url_mode,stall,selection_method,pdal_env,feedback):
        diagnostics=[];strategies=self._url_sets(records,url_mode)
        pdal_timeout=min(stall if stall>0 else 30,30)
        feedback.pushInfo(f'Diagnostic HTTP puis PDAL de {len(records)} source(s) pour {edition}')
        feedback.pushInfo('Règle stricte : un timeout du diagnostic rapide est indéterminé; seule l’extraction réelle confirme un trou de couverture.')
        for index,record in enumerate(records,1):
            source_result={'id':record.id,'tile_key':record.tile_key,'catalogue_edition':record.edition,'resource_date':record.resource_date,'url_npl':record.url,'selection_method':selection_method,'attempts':[],'selected_strategy':None,'status':'unknown'}
            feedback.pushInfo(f'Source {index}/{len(records)} — {record.id} — dalle {record.tile_key} — catalogue {record.edition} → ressource {record.resource_date or "non datée"}')
            success=False;has_http=False;has_timeout=False
            for strategy,urls in strategies:
                url=urls[index-1]
                feedback.pushInfo(f'  {strategy} — test HTTP léger par la pile réseau QGIS')
                http=probe_url(url,feedback)
                for range_check in http['ranges']:
                    feedback.pushInfo(f"  Range {range_check['range']} : HTTP {range_check['status']}, Content-Range={range_check['content_range'] or 'absent'}, octets={range_check['bytes_received']}, compatible={range_check['compatible']}")
                if not http['http_accessible']:
                    feedback.reportError(f'  HTTP inaccessible avec {strategy} : HEAD={http["head_message"]}',False)
                    source_result['attempts'].append({'strategy':strategy,'url':url,'http':http,'pdal_tested':False,'readable':False,'diagnostic':'http_inaccessible'})
                    continue
                has_http=True
                if not http['range_compatible']:
                    feedback.reportError(f'  HTTP accessible mais requêtes Range incompatibles avec readers.copc pour {strategy}.',False)
                    source_result['attempts'].append({'strategy':strategy,'url':url,'http':http,'pdal_tested':False,'readable':False,'diagnostic':'range_incompatible'})
                    continue
                feedback.pushInfo(f'  Deux requêtes Range valides; test PDAL rapide limité à {pdal_timeout} s')
                code,log,duration,status=run_command_timeout([pdal,'info','--metadata',url],feedback,f'Source {index}/{len(records)} {record.id}',pdal_timeout,env=pdal_env)
                valid_json=False
                if code==0:
                    try:valid_json=isinstance(json.loads(log),dict)
                    except Exception:valid_json=False
                has_timeout=has_timeout or status=='timeout'
                attempt={'strategy':strategy,'url':url,'http':http,'pdal_tested':True,'pdal_code':code,'pdal_status':status,'duration_seconds':round(duration,1),'metadata_json':valid_json,'log_tail':log[-1600:],'readable':code==0 and valid_json,'diagnostic':'readable' if code==0 and valid_json else ('indeterminate_timeout' if status=='timeout' else 'pdal_error')}
                source_result['attempts'].append(attempt)
                if attempt['readable']:
                    source_result['selected_strategy']=strategy;source_result['status']='validated';success=True
                    feedback.pushInfo(f'  COPC validé par PDAL avec {strategy} en {duration:.1f} s')
                    break
                if status=='timeout':
                    feedback.pushWarning(f'  HTTP accessible; diagnostic PDAL indéterminé après {pdal_timeout} s avec {strategy}. Validation reportée à l’extraction réelle.') if hasattr(feedback,'pushWarning') else feedback.pushInfo(f'  AVERTISSEMENT : diagnostic PDAL indéterminé avec {strategy}; validation reportée à l’extraction réelle.')
                else:
                    feedback.reportError(f'  HTTP accessible mais erreur PDAL avec {strategy} : état={status}, code={code}.',False)
            if not success and has_http and has_timeout:
                source_result['status']='indeterminate';source_result['selected_strategy']='validation_reported_to_extraction'
                feedback.pushInfo(f'  Source {record.id} conservée pour l’extraction complète : HTTP accessible, diagnostic rapide indéterminé.')
                diagnostics.append(source_result)
                continue
            source_result['readable']=success;diagnostics.append(source_result)
            if not success:
                feedback.reportError('=== TROU DE COUVERTURE CONFIRMÉ AVANT EXTRACTION — MODE STRICT ===',False)
                feedback.reportError(f'Dalle : {record.tile_key}; métadonnée : {record.id}; catalogue : {record.edition}; ressource : {record.resource_date or "non datée"}',False)
                feedback.reportError('Toutes les stratégies HTTP/PDAL ont produit un échec explicite. Aucun COPC incomplet ne sera produit.',False)
                details=' | '.join(a['strategy']+': HTTP='+str(a['http']['http_accessible'])+', Range='+str(a['http'].get('range_compatible'))+', diagnostic='+a.get('diagnostic','') for a in source_result['attempts'])
                raise QgsProcessingException(f'Trou de couverture confirmé sur la dalle {record.tile_key} ({record.id}). '+details)
        validated=sum(1 for item in diagnostics if item['status']=='validated');indeterminate=sum(1 for item in diagnostics if item['status']=='indeterminate')
        feedback.pushInfo(f'Diagnostic terminé : {validated} source(s) validée(s), {indeterminate} source(s) indéterminée(s) transmises à l’extraction réelle.')
        return diagnostics
    def processAlgorithm(self,p,c,f):
        pdal=shutil.which('pdal')
        if not pdal:raise QgsProcessingException('pdal introuvable')
        f.pushInfo('PDAL utilisé : '+pdal)
        pdal_env,proxy_info=build_pdal_environment(pdal)
        if proxy_info['proxy_active']:
            f.pushInfo(f"Réseau PDAL : proxy {proxy_info['host']}:{proxy_info['port']} (source : {proxy_info['source']}; transmis au subprocess : {'oui' if proxy_info['proxy_injected'] else 'non, variables déjà présentes'}; exclusions : {proxy_info['excluded_count']})")
        else:
            f.pushInfo('Réseau PDAL : aucun proxy détecté; connexion directe.')
        if proxy_info['ca_bundle']:
            f.pushInfo(f"Certificats TLS PDAL : ARBITER_CA_INFO={proxy_info['ca_bundle']} ({proxy_info['ca_source']})")
        else:
            f.pushWarning('Aucun bundle de certificats CA trouvé pour PDAL : les lectures HTTPS risquent d’échouer (définir ARBITER_CA_INFO).') if hasattr(f,'pushWarning') else f.pushInfo('AVERTISSEMENT : aucun bundle CA trouvé pour PDAL.')
        f.pushInfo('Phase 1/3 — Inventaire réel des éditions');f.setProgress(3);extent,source,all_records,groups,wfs_url=self.inventory(p,c,f);jobs=build_jobs(all_records,self.parameterAsEnum(p,self.MODE,c),self.parameterAsString(p,self.SEL,c));f.pushInfo('Productions retenues : '+', '.join(job[0] for job in jobs));folder=self.output_folder(p,c,f);prefix=re.sub(r'[^\w-]','_',self.parameterAsString(p,self.PREFIX,c)) or 'lidar_hd';resolution=self.parameterAsDouble(p,self.R,c);url_mode=self.parameterAsEnum(p,self.URL_MODE,c);diagnostic=self.parameterAsBool(p,self.DIAG,c);stall=self.parameterAsInt(p,self.STALL,c);total_readers=sum(len(job[1]) for job in jobs);prepared=0;results=[]
        f.pushInfo(f'Phase 2/3 — Préparation de {total_readers} source(s) pour {len(jobs)} édition(s)');f.setProgress(12)
        for edition_index,(edition,records,selection_method) in enumerate(jobs,1):
            effective_urls,range_checks=self._select_effective_urls(records,url_mode,f)
            f.pushInfo('Test réseau PDAL avec le même environnement que la pipeline (première source, 30 s maximum)')
            test_env=dict(pdal_env);test_env['ARBITER_VERBOSE']='1'
            test_code,test_log,test_duration,test_status=run_command_timeout([pdal,'info','--metadata',effective_urls[0]],f,'Test réseau PDAL',30,env=test_env,quiet=True)
            if test_code==0:
                f.pushInfo(f'Test réseau PDAL réussi en {test_duration:.1f} s.')
            elif test_status=='timeout':
                f.pushWarning('Test réseau PDAL indéterminé après 30 s; poursuite avec l’extraction complète.') if hasattr(f,'pushWarning') else f.pushInfo('AVERTISSEMENT : test réseau PDAL indéterminé; poursuite de l’extraction complète.')
            else:
                f.reportError('Test réseau PDAL en échec explicite; la pipeline complète est tout de même tentée pour conserver le diagnostic strict.',False)
            if test_code!=0:
                for line in key_network_lines(test_log):f.pushInfo('  PDAL réseau : '+line)
                for hint in classify_pdal_log(test_log):f.reportError('  Piste : '+hint,False)
            source_diagnostics=self._diagnose_sources(pdal,records,extent,source,c,resolution,folder,prefix,edition,url_mode,stall,selection_method,pdal_env,f) if diagnostic else []
            for record in records:
                crs,note=resolve_crs(record.planimetric);f.pushInfo(f'{record.id} — dalle {record.tile_key} — catalogue {record.edition} → ressource {record.resource_date or "non datée"} — {record.planimetric} → {crs.authid()}');prepared+=1;f.setProgress(12+int(28*prepared/max(1,total_readers)))
            output=os.path.abspath(os.path.join(folder,f'{prefix}_{edition}.copc.laz'));pipeline=os.path.abspath(os.path.join(folder,f'{prefix}_{edition}_pipeline.json'));f.pushInfo('COPC local de sortie : '+output);f.pushInfo('Pipeline locale : '+pipeline);attempts=[];success=False
            plan=attempt_plan(effective_urls,self._url_sets(records,url_mode))
            for attempt_index,(strategy,urls) in enumerate(plan,1):
                if f.isCanceled():raise QgsProcessingException('Traitement annulé.')
                if os.path.exists(output):
                    try:os.remove(output)
                    except OSError:pass
                self._build_pipeline(records,urls,extent,source,c,resolution,output,pipeline,edition,wfs_url,selection_method)
                f.pushInfo(f'Phase 3/3 — Édition {edition_index}/{len(jobs)} : {edition} — tentative {attempt_index}/{len(plan)} : {strategy} ({len(urls)} source(s), ex. {urls[0]})')
                base=40;span=55/len(jobs);f.setProgress(int(base+span*(edition_index-1)));code,log,duration,status=run_pipeline([pdal,'pipeline',pipeline],output,f,'Édition '+edition+' / '+strategy,15,stall,env=pdal_env)
                attempts.append({'strategy':strategy,'urls':urls,'hints':classify_pdal_log(log),'code':code,'duration_seconds':round(duration,1),'status':status,'log_tail':log[-1200:]})
                if code==0 and os.path.exists(output):
                    success=True;break
                if code==-1:raise QgsProcessingException('Traitement annulé pendant PDAL.')
                f.reportError(f'Échec {strategy} pour l’édition {edition}, code {code} ({status}).'+(' Passage au repli.' if attempt_index<len(plan) else ' Aucun repli restant.'),False)
                for hint in classify_pdal_log(log):f.reportError('  Piste : '+hint,False)
                f.pushInfo('  Journal PDAL (fin) : '+log[-600:].replace(chr(10),' | '))
                if os.path.exists(output):
                    try:os.remove(output)
                    except OSError:pass
            if not success:
                details='\n'.join(a['strategy']+': '+a['log_tail'] for a in attempts)
                raise QgsProcessingException('=== TROU DE COUVERTURE CONFIRMÉ PAR L’EXTRACTION RÉELLE — MODE STRICT ===\nProduction : '+edition+'\nAucun COPC incomplet ne sera produit.\n'+details)
            size=os.path.getsize(output);f.pushInfo(f'Édition {edition} terminée avec {strategy} : {duration:.1f} s, {size/1048576:.1f} Mio');results.append({'production':edition,'selection_method':selection_method,'catalogue_editions':sorted(set(r.edition for r in records),reverse=True),'resource_dates':sorted(set(r.resource_date for r in records if r.resource_date),reverse=True),'output':output,'pipeline':pipeline,'sources':len(records),'url_strategy':strategy,'range_preflight':range_checks,'source_diagnostics':source_diagnostics,'attempts':attempts,'duration_seconds':round(duration,1),'size_bytes':size});f.setProgress(int(base+span*edition_index))
            if self.parameterAsBool(p,self.L,c):
                layer=QgsPointCloudLayer(output,f'{prefix}_{edition}','copc')
                if not layer.isValid():layer=QgsPointCloudLayer(output,f'{prefix}_{edition}','pdal')
                if layer.isValid():f.pushInfo('Rendu 2D explicite : '+apply_default_renderer(layer))
                if layer.isValid():c.temporaryLayerStore().addMapLayer(layer);c.addLayerToLoadOnCompletion(layer.id(),QgsProcessingContext.LayerDetails(f'{prefix}_{edition}',c.project(),self.OUT))
                else:f.reportError('COPC créé mais chargement impossible : '+output,False)
        manifest=os.path.join(folder,prefix+'_manifest.json')
        with open(manifest,'w',encoding='utf-8') as stream:json.dump({'productions':[job[0] for job in jobs],'selection_mode':self.parameterAsEnum(p,self.MODE,c),'results':results},stream,ensure_ascii=False,indent=2)
        f.setProgress(100);f.pushInfo('Toutes les éditions sélectionnées ont été produites. Manifeste : '+manifest);return {self.M:manifest,self.OUT:folder}

