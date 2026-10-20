import os,queue,subprocess,threading,time
from .pdal_support import progress_message

def hidden_options():
    if os.name!='nt':return {}
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=subprocess.SW_HIDE
    return {'startupinfo':info,'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)}

def _start(command,env):
    return subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,env=env,**hidden_options())

def _reader(stream,line_queue):
    try:
        for line in iter(stream.readline,''):
            line_queue.put(line.rstrip())
    finally:
        line_queue.put(None)

def _drain(line_queue,lines,feedback,echo=True):
    while True:
        try:item=line_queue.get_nowait()
        except queue.Empty:return
        if item is None:return
        lines.append(item)
        if item and echo:feedback.pushInfo('PDAL : '+item)

def run_pipeline(command,output_path,feedback,label,poll_seconds=15,stall_seconds=120,env=None):
    process=_start(command,env);line_queue=queue.Queue();threading.Thread(target=_reader,args=(process.stdout,line_queue),daemon=True).start()
    started=time.monotonic();last_report=started;last_growth=started;last_size=-1;last_reported_size=0;lines=[]
    while process.poll() is None:
        _drain(line_queue,lines,feedback)
        if feedback.isCanceled():
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            _drain(line_queue,lines,feedback)
            return -1,'\n'.join(lines),time.monotonic()-started,'cancelled'
        now=time.monotonic();exists=os.path.exists(output_path);size=os.path.getsize(output_path) if exists else 0
        if size!=last_size:last_size=size;last_growth=now
        if now-last_report>=poll_seconds:
            feedback.pushInfo(f'{label} — '+progress_message(now-started,exists,size,last_reported_size,now-last_growth))
            last_report=now;last_reported_size=size
        if stall_seconds and exists and now-last_growth>=stall_seconds:
            feedback.reportError(f'{label} — interruption après {int(now-last_growth)} s sans croissance du fichier local.',False)
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            _drain(line_queue,lines,feedback)
            return -3,'\n'.join(lines),now-started,'stalled'
        time.sleep(0.25)
    _drain(line_queue,lines,feedback)
    return process.returncode,'\n'.join(lines),time.monotonic()-started,'finished'

def run_command_timeout(command,feedback,label,timeout_seconds,env=None,quiet=False):
    process=_start(command,env);line_queue=queue.Queue();threading.Thread(target=_reader,args=(process.stdout,line_queue),daemon=True).start()
    started=time.monotonic();last_report=-1;lines=[]
    while process.poll() is None:
        _drain(line_queue,lines,feedback,not quiet)
        if feedback.isCanceled():
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            _drain(line_queue,lines,feedback,not quiet)
            return -1,'\n'.join(lines),time.monotonic()-started,'cancelled'
        elapsed=time.monotonic()-started
        if int(elapsed)//15!=last_report:
            last_report=int(elapsed)//15;feedback.pushInfo(f'{label} — PDAL actif : {int(elapsed)} s')
        if timeout_seconds and elapsed>=timeout_seconds:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            _drain(line_queue,lines,feedback,not quiet)
            return -2,'\n'.join(lines),elapsed,'timeout'
        time.sleep(0.25)
    _drain(line_queue,lines,feedback,not quiet)
    return process.returncode,'\n'.join(lines),time.monotonic()-started,'finished'
