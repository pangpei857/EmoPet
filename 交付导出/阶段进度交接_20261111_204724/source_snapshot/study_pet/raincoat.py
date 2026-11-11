"""Render the supplied raincoat illustration without modifying its source file.

The source has a baked checkerboard. A cached painter clipping region excludes
that background and the detached leaf. All motion is applied at render time.
"""
from collections import deque
from functools import lru_cache
import math
from statistics import median
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygon, QRegion

SOURCE_WIDTH, SOURCE_HEIGHT = 736, 800
EYES = ((QRectF(213, 318, 43, 61), -9), (QRectF(351, 351, 56, 64), 10))
EYE_CENTER = (306.75 * 280 / SOURCE_WIDTH, 365.75 * 300 / SOURCE_HEIGHT)


def _neighbors(index, width, count):
    x = index % width
    if x:yield index-1
    if x+1<width:yield index+1
    if index>=width:yield index-width
    if index+width<count:yield index+width


def character_region(image):
    """Find the largest illustrated component, retaining its internal highlights."""
    rgb=image.convertToFormat(QImage.Format.Format_RGB888)
    pixels=bytes(rgb.constBits());width,height=rgb.width(),rgb.height()
    count=width*height;gray=bytearray(count);stride=rgb.bytesPerLine()
    for y in range(height):
        for x in range(width):
            offset=y*stride+x*3;r,g,b=pixels[offset:offset+3]
            gray[y*width+x]=min(r,g,b)>=200 and max(r,g,b)-min(r,g,b)<=16
    seen=bytearray(count);background=bytearray(count)
    for start in range(count):
        if not gray[start] or seen[start]:continue
        seen[start]=1;queue=deque([start]);component=[];edge=False
        while queue:
            index=queue.popleft();component.append(index)
            x=index%width
            if index<width or index>=count-width or x==0 or x==width-1:edge=True
            for other in _neighbors(index,width,count):
                if gray[other] and not seen[other]:seen[other]=1;queue.append(other)
        # Small isolated bright flecks belong to the glossy raincoat and eyes.
        if edge or len(component)>420:
            for index in component:background[index]=1
    seen=bytearray(count);largest=[]
    for start in range(count):
        if background[start] or seen[start]:continue
        queue=deque([start]);seen[start]=1;component=[]
        while queue:
            index=queue.popleft();component.append(index)
            for other in _neighbors(index,width,count):
                if not background[other] and not seen[other]:seen[other]=1;queue.append(other)
        if len(component)>len(largest):largest=component
    if len(largest)<count*.1:raise RuntimeError("The raincoat illustration could not be isolated")
    mask=bytearray(count)
    for index in largest:mask[index]=1
    region=QRegion()
    for y in range(height):
        x=0
        while x<width:
            if not mask[y*width+x]:x+=1;continue
            start=x
            while x<width and mask[y*width+x]:x+=1
            region=region.united(QRegion(start,y,x-start,1))
    return region


@lru_cache(maxsize=1)
def artwork():
    source=Path(__file__).resolve().parent.parent/'assets/raincoat-reference.png'
    image=QImage(str(source))
    if image.isNull():raise RuntimeError(f"Missing character artwork: {source}")
    if image.size().width()!=SOURCE_WIDTH or image.size().height()!=SOURCE_HEIGHT:
        raise RuntimeError("Unexpected raincoat artwork dimensions")
    region=character_region(image)
    return image,region


def hit_shape():
    _,region=artwork()
    shape=QPainterPath();shape.addRegion(region)
    from PySide6.QtGui import QTransform
    return QTransform.fromScale(280/SOURCE_WIDTH,300/SOURCE_HEIGHT).map(shape)


@lru_cache(maxsize=1)
def rig_regions():
    _,region=artwork()
    left=region.intersected(QRegion(198,15,100,229))
    right=region.intersected(QRegion(QPolygon([QPoint(x,y) for x,y in
        ((424,235),(508,191),(647,170),(725,175),(725,235),(602,277),(476,308),(435,284))])))
    tail=region.intersected(QRegion(QPolygon([QPoint(x,y) for x,y in
        ((447,563),(488,546),(720,480),(730,650),(520,790),(421,768),(411,737),(466,706))])))
    # Small overlaps keep the ear and tail roots covered while those pieces move.
    body=region.subtracted(left.intersected(QRegion(198,15,100,214)))
    body=body.subtracted(right.subtracted(QRegion(425,245,55,70)))
    body=body.subtracted(tail.subtracted(QRegion(410,700,50,60)))
    return body,left,right,tail


def _layer(p,image,region,anchor,angle):
    p.save();p.translate(*anchor);p.rotate(angle);p.translate(-anchor[0],-anchor[1])
    p.setClipRegion(region);p.drawImage(QPoint(0,0),image);p.restore()


@lru_cache(maxsize=2)
def _lid_texture(index):
    image,_=artwork();rect,rotation=EYES[index]
    width,height=round(rect.width()+16),round(rect.height()+16)
    texture=QImage(width,height,QImage.Format.Format_ARGB32)
    texture.fill(Qt.GlobalColor.transparent);p=QPainter(texture)
    angle=math.radians(rotation);cx,cy=rect.center().x(),rect.center().y()
    def sample(u,v):
        sx=cx+u*math.cos(angle)-v*math.sin(angle)
        sy=cy+u*math.sin(angle)+v*math.cos(angle)
        colors=[image.pixelColor(max(0,min(SOURCE_WIDTH-1,round(sx+dx))),max(0,min(SOURCE_HEIGHT-1,round(sy+dy)))).getRgb()[:3]
                for dx,dy in ((0,0),(-2,0),(2,0),(0,-2),(0,2))]
        return QColor(*(round(median(c[channel] for c in colors)) for channel in range(3)))
    for row in range(height):
        v=row+.5-height/2
        chord=width/2*math.sqrt(max(0.,1-(v/(height/2))**2))
        gradient=QLinearGradient(width/2-chord,row,width/2+chord,row)
        gradient.setColorAt(0,sample(-chord-2,v));gradient.setColorAt(1,sample(chord+2,v))
        p.fillRect(QRectF(0,row,width,1),gradient)
    p.end();return texture


def _eye(p,image,rect,rotation,gaze,closed,index):
    center=rect.center();p.save();p.translate(center);p.rotate(rotation)
    eye=QPainterPath()
    margin=8 if closed else 0
    aperture=QRectF(-rect.width()/2-margin,-rect.height()/2-margin,rect.width()+margin*2,rect.height()+margin*2)
    eye.addEllipse(aperture)
    p.setClipPath(eye,Qt.ClipOperation.IntersectClip)
    if closed:
        # Match the surrounding face's shading rather than pasting a visibly
        # brighter oval from the forehead over the painted eyes.
        p.drawImage(aperture,_lid_texture(index))
        p.setPen(QPen(QColor('#70502B'),2.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        lid=QPainterPath();lid.moveTo(-rect.width()*.4,0)
        lid.cubicTo(-rect.width()*.15,rect.height()*.14,rect.width()*.18,rect.height()*.13,rect.width()*.4,-2)
        p.drawPath(lid)
    else:
        # The original painted iris is reprojected inside its original eye outline.
        # A small texture margin preserves the original painted highlights.
        p.fillPath(eye,QColor('#74452C'))
        dx,dy=gaze[0]*6.0,gaze[1]*6.5
        target=QRectF(-rect.width()*.56+dx,-rect.height()*.56+dy,rect.width()*1.12,rect.height()*1.12)
        p.drawImage(target,image,rect)
    p.restore()


def draw_character(p,bounds,time_s,mood,gaze,hovering):
    image,region=artwork()
    body,left,right,tail=rig_regions()
    p.save();p.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.SmoothPixmapTransform)
    p.translate(bounds.x(),bounds.y());p.scale(bounds.width()/280,bounds.height()/300)
    # Breathing and reactions pivot around the feet to keep the character grounded.
    bounce=-abs(math.sin(time_s*7))*5 if mood in {'encourage','remind','tail'} else math.sin(time_s*2.3)*.9
    p.translate(140,284+bounce)
    if mood=='care':p.rotate(-3+math.sin(time_s*2)*.8)
    elif mood=='poke':p.rotate(math.sin(time_s*14)*1.4)
    elif mood=='pet':p.rotate(math.sin(time_s*3)*1.2)
    elif hovering:p.rotate(math.sin(time_s*2.7)*.35)
    p.scale(1+math.sin(time_s*2.3)*.0015,1+math.sin(time_s*2.3)*.003)
    p.translate(-140,-284)
    p.save();p.scale(280/SOURCE_WIDTH,300/SOURCE_HEIGHT)
    tail_angle=math.sin(time_s*2.1)*(4 if mood=='tail' else 1.7)
    ear_angle=math.sin(time_s*(8 if mood=='remind' else 2.4))*(3 if mood=='remind' else 1.1)
    _layer(p,image,tail,(442,726),tail_angle)
    _layer(p,image,left,(245,240),ear_angle)
    _layer(p,image,right,(454,268),-ear_angle*.75)
    p.setClipRegion(body);p.drawImage(QPoint(0,0),image)
    closed=mood in {'pet','poke','encourage','rest'} or time_s%5.3>5.16
    for index,(rect,angle) in enumerate(EYES):_eye(p,image,rect,angle,gaze,closed,index)
    p.restore();p.restore()
