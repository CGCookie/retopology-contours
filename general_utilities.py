'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

#This class makes it easier to be install location independent
import sys, os
import bpy
import time
import inspect
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion

class AddonLocator(object):
    def __init__(self, f=None):
        self.fullInitPath = f if f else __file__
        self.FolderPath = os.path.dirname(self.fullInitPath)
        self.FolderName = os.path.basename(self.FolderPath)
    
    def AppendPath(self):
        sys.path.append(self.FolderPath)
        print("Addon path has been registered into system path for this session")

class Profiler(object):
    class ProfilerHelper(object):
        def __init__(self, pr, text):
            full_text = (pr.stack[-1].text+'^' if pr.stack else '') + text
            assert full_text not in pr.d_start, '"%s" found in profiler already?'%text
            self.pr = pr
            self.text = full_text
            self._is_done = False
            self.pr.d_start[self.text] = time.time()
            self.pr.stack += [self]
        def __del__(self):
            if not self._is_done:
                dprint('WARNING: calling ProfilerHelper.done!')
                self.done()
        def done(self):
            assert self.pr.stack[-1] == self
            assert not self._is_done
            self.pr.stack.pop()
            self._is_done = True
            st = self.pr.d_start[self.text]
            en = time.time()
            self.pr.d_times[self.text] = self.pr.d_times.get(self.text,0) + (en-st)
            self.pr.d_count[self.text] = self.pr.d_count.get(self.text,0) + 1
            del self.pr.d_start[self.text]
    
    def __init__(self):
        self.d_start = {}
        self.d_times = {}
        self.d_count = {}
        self.stack = []
    
    def start(self, text=None):
        if not text:
            st = inspect.stack()
            filename = os.path.split(st[1][1])[1]
            linenum  = st[1][2]
            fnname   = st[1][3]
            text = '%s (%s:%d)' % (fnname, filename, linenum)
        return self.ProfilerHelper(self, text)
    
    def __del__(self):
        self.printout()
    
    def printout(self):
        dprint('Profiler:')
        for text in sorted(self.d_times):
            tottime = self.d_times[text]
            totcount = self.d_count[text]
            calls = text.split('^')
            if len(calls) == 1:
                t = text
            else:
                t = '    '*(len(calls)-2) + ' \\- ' + calls[-1]
            dprint('  %6.2f / %3d = %6.2f - %s' % (tottime, totcount, tottime/totcount, t))
        dprint('')

profiler = Profiler()


def range_mod(m):
    for i in range(m): yield(i,(i+1)%m)

def iter_running_sum(lw):
    s = 0
    for w in lw:
        s += w
        yield (w,s)

def dprint(s, l=2):
    AL = AddonLocator()
    settings = bpy.context.user_preferences.addons[AL.FolderName].preferences
    if settings.debug >= l: print('DEBUG(%i): %s' % (l, s))

def ray_cast_path(context, ob, screen_coords):
    rgn  = context.region
    rv3d = context.space_data.region_3d
    mx   = ob.matrix_world
    imx  = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co),r2d_vector(rgn, rv3d, co).normalized()) for co in screen_coords]
    back = 0 if rv3d.is_perspective else 1
    mult = 100 * (1 if rv3d.is_perspective else -1)
    
    hits = [ob.ray_cast(imx*(o-d*back*mult), imx*(o+d*mult)) for o,d in rays]
    world_coords = [mx*hit[0] for hit in hits if hit[2] != -1]
    
    return world_coords

def ray_cast_stroke(context, ob, stroke):
    '''
    strokes have form [((x,y),p)] with a pressure or radius value
    
    returns list [Vector(x,y,z), p] leaving the pressure/radius value untouched
    does drop any values that do not successrfully ray_cast
    '''
    rgn  = context.region
    rv3d = context.space_data.region_3d
    mx   = ob.matrix_world
    imx  = mx.inverted()
    
    r2d_origin = region_2d_to_origin_3d
    r2d_vector = region_2d_to_vector_3d
    
    rays = [(r2d_origin(rgn, rv3d, co[0]),r2d_vector(rgn, rv3d, co[0]).normalized()) for co in stroke]
    
    back = 0 if rv3d.is_perspective else 1
    mult = 100 * (1 if rv3d.is_perspective else -1)
    
    hits = [ob.ray_cast(imx*(o-d*back*mult), imx*(o+d*mult)) for i, (o,d) in enumerate(rays)]
    world_stroke = [(mx*hit[0],stroke[i][1])  for i, hit in enumerate(hits) if hit[2] != -1]
    
    return world_stroke

def frange(start, end, step):
    v = start
    if step > 0:
        while v < end:
            yield v
            v += step
    else:
        while v > end:
            yield v
            v += step

def vector_compwise_mult(a,b):
    return Vector(ax*bx for ax,bx in zip(a,b))

def get_object_length_scale(o):
    sc = o.scale
    bbox = [vector_compwise_mult(sc,Vector(bpt)) for bpt in o.bound_box]
    l = (min(bbox)-max(bbox)).length
    return l
