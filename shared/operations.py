"""Copy circulation and operations RPC helpers."""
from shared.api import ApiError
MIGRATION='migrations/20260930115934_library_operations.sql'

def operations(api,user,action,data=None):
    try:return api.rpc('library_operations',{'p_token':user.get('token',''),'p_action':action,'p_data':data or {}})
    except ApiError as exc:
        if 'PGRST202' in str(exc) or 'Could not find the function' in str(exc):raise ApiError(f'Library operations need database setup. Apply {MIGRATION} after migration 003, then sign in again.') from exc
        raise

def station_operations(host,action,data=None):
    return host.api.rpc('library_operations_station',{'p_station':host.cfg['STATION_CODE'],'p_token':host.cfg['STATION_TOKEN'],'p_action':action,'p_data':data or {}})

def labels_pdf(path,copies):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.graphics import renderPDF
    from reportlab.lib.utils import simpleSplit
    if not copies:raise ValueError('Select at least one copy.')
    c=canvas.Canvas(str(path),pagesize=A4);w,h=A4
    for i,row in enumerate(copies):
        if i and i%12==0:c.showPage()
        x=18+(i%2)*(w/2);y=h-18-(i%12//2)*132
        c.setStrokeColorRGB(.7,.78,.88);c.rect(x,y-122,w/2-30,122)
        c.setFont('Helvetica-Bold',9)
        for j,line in enumerate(simpleSplit(str(row['title']),'Helvetica-Bold',9,175)[:2]):c.drawString(x+8,y-14-j*11,line)
        c.setFont('Helvetica',8);c.drawString(x+8,y-40,'Shelf: '+str(row.get('shelf') or 'Unassigned'))
        accession=str(row['accession']);c.drawString(x+8,y-52,accession[:54]);c.drawString(x+8,y-64,'Condition: '+str(row.get('condition','good')))
        qr=createBarcodeDrawing('QR',value=accession,width=60,height=60);renderPDF.draw(qr,c,x+w/2-96,y-70)
        barcode=createBarcodeDrawing('Code128',value=accession,barHeight=24,humanReadable=False)
        c.saveState();c.translate(x+8,y-100);c.scale(min(1,(w/2-50)/barcode.width),1);renderPDF.draw(barcode,c,0,0);c.restoreState()
    c.save()
