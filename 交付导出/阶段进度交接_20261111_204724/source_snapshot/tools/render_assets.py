"""Render the current character icon and four-state preview."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
from study_pet.pikachu import draw_pikachu, pet_icon

root=Path(__file__).resolve().parent.parent
app=QApplication.instance() or QApplication([])
(root/'assets').mkdir(exist_ok=True)
(root/'.artifacts').mkdir(exist_ok=True)
if not pet_icon().pixmap(256,256).save(str(root/'assets/pikachu.ico')):
    raise RuntimeError('Could not write the application icon')
image=QImage(1120,400,QImage.Format.Format_ARGB32)
image.fill(QColor('#F8F4E8'))
p=QPainter(image)
for i,(mood,label) in enumerate([('idle','待机 · 呼吸眨眼'),('care','关心 · 歪头爱心'),('remind','提醒 · 轻跳闹钟'),('encourage','鼓励 · 跳跃星星')]):
    draw_pikachu(p,QRectF(i*280+10,24,260,300),.8,mood)
    p.setPen(QColor('#77521E'));p.setFont(QFont('Microsoft YaHei UI',12))
    p.drawText(QRectF(i*280,344,280,40),Qt.AlignmentFlag.AlignCenter,label)
p.end()
if not image.save(str(root/'.artifacts/pikachu-actions.png')):raise RuntimeError('Could not save actions')
print('Rendered icon and four-state preview')
