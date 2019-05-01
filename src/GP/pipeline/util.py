#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pathlib
from six.moves import configparser
import os
import time
import sys
import subprocess
import colorama
import numpy as np

from . import parse_ompl

# CAVEAT: sys.executable is empty string on Condor Worker node.
PYTHON = sys.executable
#assert PYTHON is not None and PYTHON != '', 'Cannot find python through sys.executable, which is {}'.format(PYTHON)

WORKSPACE_SIGNATURE_FILE = '.puzzle_workspace'
# Core files
WORKSPACE_CONFIG_FILE = 'config'
CONDOR_TEMPLATE = 'template.condor'
PUZZLE_CFG_FILE = 'puzzle.cfg' # In every puzzle directory
# Top level Directories
TRAINING_DIR = 'train'
TESTING_DIR = 'test'
CONDOR_SCRATCH = 'condor_scratch'
NEURAL_SCRATCH = 'nn_scratch'
SOLVER_SCRATCH = 'solver_scratch'
# Protocol files/directories
# Used by multiple pipeline parts
#
# Note: we use UPPERCASE KEY to indicate this is training data/ground truth.
KEY_FILE = os.path.join(TRAINING_DIR, 'KEY.npz')
UV_DIR = os.path.join(CONDOR_SCRATCH, 'training_key_uvproj')

PIXMARGIN = 2

KEY_PREDICTION = 'forest_roots.npz'
PDS_SUBDIR = 'pds'

RDT_FOREST_ALGORITHM_ID = 15

'''
WORKSPACE HIERARCHY

workspace/
+-- .puzzle_workspace   # Signature
+-- config              # Runtime configuration
+-- template.condor     # Template HTCondor submission file
+-- train/              # training data
|   +-- puzzle.cfg      # OMPL cfg
|   +-- <Env>.obj       # .OBJ file for environment geometry, name may vary
|   +-- <Rob>.obj       # .OBJ file for robot geometry, name may vary
|   +-- KEY.npz         # Detetcted key configurations from the training puzzle
|   +-- env_chart.npz   # Weight Chart for environment geometry
|   +-- env_chart.png   #  ... in PNG format
|   +-- <Env>.png       #  Screened weight in PNG format ready for pyosr to load
|   +-- rob_chart.npz   # Weight Chart for robot geometry
|   +-- rob_chart.png   #  ... in PNG format
|   +-- <Rob>.png       #  Screened weight in PNG format ready for pyosr to load
+-- test/               # testing data
|   +-- <Puzzle 1>/     # Each puzzle has its own directory
|   |   +-- puzzle.cfg  # OMPL cfg
|   |   +-- <Env>.obj   # .OBJ file for environment geometry, name may vary
|   |   +-- <Rob>.obj   # .OBJ file for robot geometry, name may vary
|   |   +-- env-atex.npz# Environment surface distribution
|   |   +-- rob-atex.npz# Robot surface distribution
|   |   +-- key.npz     # sampled key configurations
|   +-- <Puzzle 2>/     # Each puzzle has its own directory
|    ...
+-- condor_scratch/     # Scratch directory that store stdin stdout stderr log generated by HTCondor
|   +-- training_trajectory     # search for the solution trajectory (a.k.a. solution path)
|   +-- training_key_can        # search for the key configuration by estimating the clearance
|   +-- training_key_touch      #
|   +-- training_key_isect      #
|   +-- training_key_uvproj     #
+-- nn_scratch/         # Scratch directory for NN checkpoints/logs
|   +-- env.pid         # PID file of the training process for env geometry
|   +-- rob.pid         # PID file of the training process for rob geometry
|   +-- rob/            # checkpoints for rob
|   +-- env/            # checkpoints for env
+-- solver_scratch/     # Scratch directory for OMPL solvers
|   +-- <Puzzle 1>/     # Each puzzle has its own directory
|   |   +-- pds/        # Predefined sample set
'''

def _load_unit_world(uw, puzzle_file):
    puzzle, config = parse_ompl.parse_simple(puzzle_file)
    uw.loadModelFromFile(puzzle.env_fn)
    uw.loadRobotFromFile(puzzle.rob_fn)
    uw.scaleToUnit()
    uw.angleModel(0.0, 0.0)
    uw.recommended_cres = config.getfloat('problem', 'collision_resolution', fallback=0.001)

def create_unit_world(puzzle_file):
    # Well this is against PEP 08 but we do not always need pyosr
    # (esp in later pipeline stages)
    # Note pyosr is a heavy-weight module with
    #   + 55 dependencies on Fedora 29 (control node)
    #   + 43 dependencies on Ubuntu 18.04 (GPU node)
    #   + 26 dependencies on Ubuntu 16.04 (HTCondor node)
    import pyosr
    uw = pyosr.UnitWorld()
    _load_unit_world(uw, puzzle_file)
    return uw

def shell(args):
    log('Running {}'.format(args))
    return subprocess.call(args)

_egl_dpy = None

def create_offscreen_renderer(puzzle_file, resolution=256):
    global _egl_dpy
    import pyosr
    if _egl_dpy is None:
        pyosr.init()
        _egl_dpy  = pyosr.create_display()
    glctx = pyosr.create_gl_context(_egl_dpy)
    r = pyosr.Renderer()
    r.pbufferWidth = resolution
    r.pbufferHeight = resolution
    r.setup()
    r.views = np.array([[0.0,0.0]], dtype=np.float32)
    _load_unit_world(r, puzzle_file)
    return r

def _rsync(from_host, from_pather, to_host, to_pather, *paths):
    # Note: do NOT use single target multiple source syntax
    #       the target varies among source paths.
    from_prefix = '' if from_host is None else from_host+':'
    to_prefix = '' if to_host is None else to_host+':'
    for rel_path in paths:
        ret = shell(['rsync', '-aR',
                     '{}{}/./{}'.format(from_prefix, from_pather(), rel_path),
                     '{}{}/'.format(to_prefix, to_pather())])

class Workspace(object):
    _egl_dpy = None

    def __init__(self, workspace_dir, init=False):
        self.workspace_dir = os.path.abspath(workspace_dir)
        log("[Workspace] created as {}".format(self.workspace_dir))
        self._config = None
        # We may cache multiple UnitWorld objects with this directory
        self._uw_dic = {}
        if not init:
            self.verify_signature()

    def get_path(self, optname):
        return self.config.get('DEFAULT', optname)

    @property
    def dir(self):
        return self.workspace_dir

    @property
    def config(self):
        if self._config is None:
            self._config = configparser.ConfigParser()
            self._config.read(self.configuration_file)
        return self._config

    @property
    def chart_resolution(self):
        return self.config.getint('DEFAULT', 'ChartReslution')

    # This function is designed to be called on non-condor hosts
    def condor_exec(self, xfile=''):
        return os.path.join(self.get_path('CondorExecPath'), xfile)

    # This function is designed to be called on condor hosts locally
    # The home directory is only known on local system
    # and hence expanduser can return correct path.
    def condor_local_exec(self, *paths):
        return os.path.abspath(os.path.expanduser(self.condor_exec(*paths)))

    def gpu_exec(self, xfile=''):
        return os.path.join(self.get_path('GPUExecPath'), xfile)

    def gpu_local_exec(self, xfile=''):
        return os.path.abspath(os.path.expanduser(self.gpu_exec(*paths)))

    def local_ws(self, *paths):
        return os.path.abspath(os.path.expanduser(os.path.join(self.workspace_dir, *paths)))

    # Get the path inside the condor workspace
    # Most code is supposed to run locally. Only use it on remote calling code!
    def condor_ws(self, *paths):
        return os.path.join(self.get_path('CondorWorkspacePath'), *paths)

    def gpu_ws(self, *paths):
        return os.path.join(self.get_path('GPUWorkspacePath'), *paths)

    @property
    def signature_file(self):
        return self.local_ws(WORKSPACE_SIGNATURE_FILE)

    def touch_signature(self):
        pathlib.Path(self.signature_file).touch()

    def verify_signature(self):
        if not os.path.isfile(self.signature_file):
            fatal("{} is not initialized as a puzzle workspace. Exiting".format(self.workspace_dir))
            exit()

    @property
    def training_dir(self):
        return self.local_ws(TRAINING_DIR)

    @property
    def training_puzzle(self):
        return self.local_ws(TRAINING_DIR, PUZZLE_CFG_FILE)

    @property
    def testing_dir(self):
        return self.local_ws(TESTING_DIR)

    @property
    def configuration_file(self):
        return self.local_ws(WORKSPACE_CONFIG_FILE)

    @property
    def condor_template(self):
        return self.local_ws(CONDOR_TEMPLATE)

    @property
    def condor_host(self):
        return self.config.get('DEFAULT', 'CondorHost')

    @property
    def gpu_host(self):
        return self.config.get('DEFAULT', 'GPUHost')

    def condor_unit_world(self, puzzle_dir):
        if puzzle_dir not in self._uw_dic:
            self._uw_dic[puzzle_dir] = create_unit_world(self.condor_ws(puzzle_dir, PUZZLE_CFG_FILE))
        return self._uw_dic[puzzle_dir]

    def remote_command(self, host, exec_path, ws_path, pipeline_part, cmd, auto_retry=True, in_tmux=False):
        script  = 'cd {}\n'.format(exec_path)
        if in_tmux:
            script += 'tmux new-session -A -s puzzle_workspace '
        script += './facade.py {ppl} --stage {cmd} {ws}'.format(ppl=pipeline_part, ws=ws_path, cmd=cmd)
        if in_tmux:
            # tmux needs a terminal
            remoter = ['ssh', '-t', host]
        else:
            remoter = ['ssh', host]
        ret = shell(remoter + [script])
        while ret != 0:
            if not auto_retry:
                return ret
            print("SSH Connection to {} is probably broken, retry after 5 secs".format(host))
            time.sleep(5)
            ret = shell(['ssh', host, script + ' --only_wait'])

    '''
    Note: directory must end with /
    '''
    def deploy_to_condor(self, *paths):
        shell(['ssh', self.condor_host, 'mkdir', '-p', self.condor_ws()])
        _rsync(None, self.local_ws, self.condor_host, self.condor_ws, *paths)

    def fetch_condor(self, *paths):
        _rsync(self.condor_host, self.condor_ws, None, self.local_ws, *paths)

    def deploy_to_gpu(self, *paths):
        shell(['ssh', self.gpu_host, 'mkdir', '-p', self.gpu_ws()])
        _rsync(None, self.local_ws, self.gpu_host, self.gpu_ws, *paths)

    def fetch_gpu(self, *paths):
        _rsync(self.gpu_host, self.gpu_ws, None, self.local_ws, *paths)

    def test_puzzle_generator(self):
        for ent in os.listdir(self.local_ws(TESTING_DIR)):
            puzzle_fn = self.local_ws(TESTING_DIR, ent, 'puzzle.cfg')
            if not os.path.isfile(puzzle_fn):
                log("Cannot find puzzle file {} continue to next dir".format(puzzle_fn))
                continue
            yield puzzle_fn, ent

def trim_suffix(fn):
    return os.path.splitext(fn)[0]

def padded(current:int, possible_max:int):
    return str(current).zfill(len(str(possible_max)))

def ask_user(question):
    check = str(input(question + " (Y/N): ")).lower().strip()
    try:
        if check[0] == 'y':
            return True
        elif check[0] == 'n':
            return False
        else:
            print('Invalid Input')
            return ask_user(question)
    except Exception as error:
        print("Please enter valid inputs")
        print(error)
        return ask_user(question)

def _colorp(color, s):
    print(color + s + colorama.Style.RESET_ALL)

def log(s):
    _colorp(colorama.Style.DIM, s)

def warn(s):
    #_colorp(colorama.Style.BRIGHT + colorama.Fore.RED, s)
    _colorp(colorama.Style.BRIGHT + colorama.Fore.YELLOW, s)

def fatal(s):
    _colorp(colorama.Style.BRIGHT + colorama.Fore.RED, s)

def ack(s):
    _colorp(colorama.Style.BRIGHT + colorama.Fore.GREEN, s)

def pwait(pid):
    if pid < 0:
        return
    return subprocess.run(['tail', '--pid={}'.format(pid), '-f', '/dev/null'])
