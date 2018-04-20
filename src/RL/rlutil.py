import vision
import config
import numpy as np
import pyosr
import threading

def get_view_cfg(args):
    VIEW_CFG = config.VIEW_CFG
    if args.viewset == 'cube':
        VIEW_CFG = [(0, 4), (90, 1), (-90, 1)]
    elif args.viewset == '14' or (not args.viewset and args.ferev >= 4):
        VIEW_CFG = config.VIEW_CFG_REV4
    elif args.viewset == '22' or (not args.viewset and args.ferev != 1):
        VIEW_CFG = config.VIEW_CFG_REV2
    view_array = vision.create_view_array_from_config(VIEW_CFG)
    if args.view >= 0:
        view_num = 1
    else:
        view_num = len(view_array)
    return view_num, view_array

_thread_local = threading.local()

def create_renderer(args):
    view_num, view_array = get_view_cfg(args)
    w = h = args.res

    dpy = getattr(_thread_local, 'egl_dpy', None)
    if dpy is None:
        dpy = pyosr.create_display()
        glctx = pyosr.create_gl_context(dpy)
        _thread_local.egl_dpy = dpy
        _thread_local.egl_ctx = glctx
    r = pyosr.Renderer()
    if args.avi:
        r.avi = True
    r.pbufferWidth = w
    r.pbufferHeight = h
    r.setup()
    r.loadModelFromFile(args.envgeo)
    r.loadRobotFromFile(args.robgeo)
    r.scaleToUnit()
    r.angleModel(0.0, 0.0)
    r.default_depth = 0.0

    if args.view >= 0:
        if args.obview >= 0:
            va = [view_array[args.obview]]
        else:
            va = [view_array[args.view]]
    else:
        va = view_array
    r.views = np.array(va, dtype=np.float32)
    return r

SC_PRED_PERMUTATION = 1
SC_ACTION_PERMUTATION = 2
