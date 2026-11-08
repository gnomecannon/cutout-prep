"""Procedural shape contracts, not photographs or botanical/accuracy benchmarks.

These deliberately include deep sinuses, teeth, narrow branches and real holes.
Real-photo visual review is separate (review_leaf_photos.py).
"""
import math

import numpy as np
from PIL import Image, ImageDraw


KINDS = ('lobed', 'serrated', 'sprig', 'damaged', 'rock')


def specimen(kind='lobed'):
    image = Image.new('RGBA', (512, 512))
    draw = ImageDraw.Draw(image)
    if kind in ('lobed', 'damaged'):
        outline = [(256,38),(280,98),(320,65),(315,137),(378,108),
                   (357,175),(427,166),(389,228),(440,250),(370,285),
                   (394,324),(326,333),(336,375),(279,363),(268,400),
                   (242,400),(230,367),(184,382),(186,338),(124,346),
                   (143,302),(76,277),(122,245),(74,199),(145,207),
                   (115,144),(184,159),(174,98),(226,127)]
        draw.polygon(outline, fill=(105,66,32,255))
        draw.polygon([(247,365),(263,365),(264,480),(251,488)], fill=(95,83,38,255))
        if kind == 'damaged':
            draw.polygon([(170,233),(183,221),(197,229),(199,244),(180,250)], fill=(0,0,0,0))
            draw.polygon([(294,300),(313,298),(322,315),(310,329),(296,323)], fill=(0,0,0,0))
    elif kind == 'serrated':
        points = [(256,40)]
        for y in range(72,390,16):
            width = 132 * math.sin(math.pi*(y-40)/370) ** .8
            points.extend([(round(256+width),y),(round(256+width-14),y+8)])
        points.append((256,416))
        for y in reversed(range(72,390,16)):
            width = 121 * math.sin(math.pi*(y-40)/370) ** .8
            points.extend([(round(256-width+13),y+8),(round(256-width),y)])
        draw.polygon(points, fill=(49,108,44,255))
        draw.polygon([(250,380),(262,380),(268,482),(256,488)],fill=(91,87,35,255))
    elif kind == 'sprig':
        draw.line([(251,482),(252,97),(260,40)], fill=(100,82,41,255), width=9)
        for side in (-1,1):
            for j,y in enumerate(range(130,410,42)):
                tip=(252+side*(110+(j%2)*35),y-65)
                draw.line([(252,y+30),tip], fill=(54,99,60,255), width=7)
                for f in (.22,.40,.58,.76,.92):
                    x=252+(tip[0]-252)*f;by=y+30+(tip[1]-y-30)*f
                    for dy in (-24,24):
                        draw.line([(round(x),round(by)),(round(x+side*22),round(by+dy-7))], fill=(45,113,65,255), width=4)
    elif kind == 'rock':
        draw.polygon([(84,184),(112,98),(195,58),(286,78),(349,58),
                      (405,131),(393,205),(445,259),(413,353),(339,401),
                      (312,456),(204,444),(168,409),(96,383),(68,289)],fill=(112,99,76,255))
    else:
        raise ValueError(kind)
    return image


def photograph(kind='lobed', *, offset=0, mirror=False):
    subject = specimen(kind)
    if mirror:
        subject = subject.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    rgba = np.array(subject)
    y,x = np.indices(rgba.shape[:2])
    paper = np.empty_like(rgba)
    shade = (x*9/512+y*5/512).astype(np.uint8)
    for channel,base in enumerate((235,232,223)):
        paper[:,:,channel] = base+shade
    paper[:,:,3] = 255
    visible = rgba[:,:,3] > 0
    paper[visible] = rgba[visible]
    # A low-contrast patch is tissue, not a photographed puncture.
    if kind in ('lobed','damaged'):
        tissue = visible & ((x-270)**2/28**2+(y-233)**2/19**2 < 1)
        paper[tissue,:3] = (116,122,114)
    result = Image.fromarray(paper).convert('RGB')
    if offset:
        shifted = Image.new('RGB',result.size,(241,237,228))
        shifted.paste(result,(offset,0));result=shifted
    return result
