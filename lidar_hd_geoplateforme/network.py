from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest,QgsProcessingException

def _headers(reply):
    result={}
    for key in reply.rawHeaderList():
        name=bytes(key).decode('latin1').lower()
        result[name]=bytes(reply.rawHeader(key)).decode('latin1')
    return result

def _status(reply):
    value=reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    try:return int(value)
    except (TypeError,ValueError):return 0

def _request(url,method,feedback,range_header=None):
    request=QNetworkRequest(QUrl(url))
    request.setRawHeader(b'User-Agent',b'QGIS-LiDAR-HD/0.5.0')
    request.setRawHeader(b'Accept',b'application/octet-stream,*/*')
    request.setRawHeader(b'Accept-Encoding',b'identity')
    if range_header:request.setRawHeader(b'Range',range_header.encode('ascii'))
    call=QgsBlockingNetworkRequest()
    code=call.head(request,False,feedback) if method=='HEAD' else call.get(request,False,feedback)
    reply=call.reply()
    return {'request':method,'range':range_header,'qgis_code':int(code),'message':call.errorMessage(),'status':_status(reply),'body':bytes(reply.content()),'headers':_headers(reply)}

def get(url,accept,feedback):
    request=QNetworkRequest(QUrl(url));request.setRawHeader(b'Accept',accept.encode());request.setRawHeader(b'User-Agent',b'QGIS-LiDAR-HD/0.5.0')
    call=QgsBlockingNetworkRequest();code=call.get(request,False,feedback);body=bytes(call.reply().content())
    if code!=QgsBlockingNetworkRequest.NoError:raise QgsProcessingException('Échec réseau QGIS : '+call.errorMessage()+' | '+body.decode('utf-8','replace')[:1200])
    return body

def _range_result(response,start,end):
    expected=end-start+1;content_range=response['headers'].get('content-range','')
    return {'range':response['range'],'status':response['status'],'qgis_code':response['qgis_code'],'message':response['message'],'bytes_received':len(response['body']),'content_range':content_range,'accept_ranges':response['headers'].get('accept-ranges',''),'content_length':response['headers'].get('content-length',''),'lasf_signature':response['body'][:4]==b'LASF' if start==0 else None,'compatible':response['status']==206 and content_range.lower().startswith(f'bytes {start}-{end}/') and len(response['body'])==expected and (start!=0 or response['body'][:4]==b'LASF')}

def probe_url(url,feedback):
    """Teste HEAD et toujours deux plages nécessaires à une lecture COPC distante."""
    head=_request(url,'HEAD',feedback)
    first=_range_result(_request(url,'GET',feedback,'bytes=0-1023'),0,1023)
    second=_range_result(_request(url,'GET',feedback,'bytes=1024-2047'),1024,2047)
    return {'url':url,'head_status':head['status'],'head_code':head['qgis_code'],'head_message':head['message'],'head_headers':head['headers'],'ranges':[first,second],'http_accessible':head['qgis_code']==QgsBlockingNetworkRequest.NoError or any(item['qgis_code']==QgsBlockingNetworkRequest.NoError for item in (first,second)),'range_compatible':first['compatible'] and second['compatible']}
