import argparse
import config
import aniconf12 as aniconf
import sys

def get_parser():
    parser = argparse.ArgumentParser(description='Process some integers.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--envgeo', help='Path to environment geometry',
            default=aniconf.env_fn)
    parser.add_argument('--robgeo', help='Path to robot geometry',
            default=aniconf.rob_fn)
    parser.add_argument('--ckptdir', help='Path for checkpoint files',
            default=None)
    parser.add_argument('--sampleout', help='Path to store generated samples',
            default='')
    parser.add_argument('--mispout', help='Path to store mispredicted samples',
            default='')
    parser.add_argument('--samplein', help='Path to load generated samples',
            default='')
    parser.add_argument('--samplein2', help='Another path to load generated samples',
            default='')
    parser.add_argument('--sampletouse',  metavar='NUMBER',
            help='Number of samples to use during the training',
            type=int, default=-1)
    parser.add_argument('--samplebase',  metavar='NUMBER',
            help='Base Number of samples to read/write',
            type=int, default=0)
    parser.add_argument('--uniqueaction',  metavar='NUMBER',
            help='Only generate a specific action when sampling actions',
            type=int, default=-1)
    parser.add_argument('--actionset', nargs='+',
            help='Set to sample actions within, -1 means all actions (0-11)',
            type=int,
            default=[-1])
    parser.add_argument('--ckptprefix', help='Prefix of checkpoint files',
            default='pretrain-d-ckpt')
    parser.add_argument('--device', help='Prefix of GT file names generated by aa-gt.py',
            default='/gpu:0')
    parser.add_argument('--batch', metavar='NUMBER',
            help='pretrain-d: Sequence length in each sample\tcuriosity-rl: T_MAX in A3C/A2C algo.',
            type=int, default=32)
    parser.add_argument('--batchnorm',
            help='Enable Batch Normalization',
            action='store_true')
    parser.add_argument('--period',
            help='Accumulated Gradient',
            type=int, default=-1)
    parser.add_argument('--samplebatching', metavar='NUMBER',
            help='Number of samples read from disk in pretrain-d',
            type=int, default=1)
    parser.add_argument('--ereplayratio', metavar='N',
            help='Set the experience replay buffer to N*batch samples. <=0 disables experience replay',
            type=int, default=-1)
    parser.add_argument('--queuemax', metavar='NUMBER',
            help='Capacity of the synchronized queue to store generated GT',
            type=int, default=32)
    parser.add_argument('--threads', metavar='NUMBER',
            help='Number of GT generation threads',
            type=int, default=1)
    parser.add_argument('--iter', metavar='NUMBER',
            help='Number of samples to generate by each thread',
            type=int, default=0)
    parser.add_argument('--istateraw', metavar='REAL NUMBER',
            nargs='+',
            help='Initial state in original scaling; format: <Trans> <W-first Quat>',
            type=float, default=[17.97,7.23,10.2,1.0,0.0,0.0,0.0])
    parser.add_argument('--amag', metavar='REAL NUMBER',
            help='Magnitude of discrete actions',
            type=float, default=0.0125 * 4)
    parser.add_argument('--vmag', metavar='REAL NUMBER',
            help='Magnitude of verifying action',
            type=float, default=0.0125 * 4 / 8)
    parser.add_argument('--gameconf',
            help='''Various game configurations:
die: Terminate after hitting obstacle.
            ''',
            nargs='*'
            choices=['die']
            default=[])
    parser.add_argument('-n', '--dryrun',
            help='Visualize the generated GT without training anything',
            action='store_true')
    parser.add_argument('--dryrun2',
            help='Visualize the generated GT without training anything (MT version)',
            action='store_true')
    parser.add_argument('--dryrun3',
            help='Only generated GT, and store the GT if --sampleout is provided',
            action='store_true')
    parser.add_argument('--elu',
            help='Use ELU instead of ReLU after each NN layer',
            action='store_true')
    parser.add_argument('--lstm',
            help='Add LSTM after feature extractor for PolNet and ValNet',
            action='store_true')
    parser.add_argument('--singlesoftmax',
            help='Do not apply softmax over member of committee. Hence only one softmax is used to finalize the prediction',
            action='store_true')
    parser.add_argument('--featnum',
            help='Size of the feature vector (aka number of features)',
            type=int, default=256)
    parser.add_argument('--imhidden',
            help='Inverse Model Hidden Layer',
            nargs='+', type=int, default=[])
    parser.add_argument('--fwhidden',
            help='Forward Model Hidder Layer',
            nargs='+', type=int, default=[1024, 1024])
    parser.add_argument('--fehidden',
            help='Feature Extractor Hidder Layer',
            nargs='+', type=int, default=[1024, 1024])
    parser.add_argument('--polhidden',
            help='Policy Network Hidder Layer',
            nargs='+', type=int, default=[1024, 1024])
    parser.add_argument('--valhidden',
            help='Value Network Hidder Layer',
            nargs='+', type=int, default=[1024, 1024])
    parser.add_argument('--eval',
            help='Evaluate the network, rather than training',
            action='store_true')
    parser.add_argument('--continuetrain',
            help='Continue an interrputed training from checkpoint. This basically loads epoch from the checkpoint. WARNING: THIS IS INCOMPATIBLE WITH --samplein',
            action='store_true')
    parser.add_argument('--ferev',
            help='Reversion of Feature Extractor',
            choices=range(1,13+1),
            type=int, default=1)
    parser.add_argument('--capture',
            help='Capture input image to summary',
            action='store_true')
    parser.add_argument('--committee',
            help='(deprecated by --viewinitckpt) Employ a committee of NNs with different weights to extract features/make decisions from different views',
            action='store_true')
    parser.add_argument('--norgbd',
            help='Do not store RGB/D images in storing the sample, to save disk spaces',
            action='store_true')
    parser.add_argument('--nosamplepreview',
            help='Do not store preview RGB images from generated samples, to save disk spaces',
            action='store_true')
    parser.add_argument('--view',
            help='Pickup one view to train. -1 means all views',
            type=int, default=-1)
    parser.add_argument('--obview',
            help='The actual view used by renderer, defaults to --view but can be different for debugging purpose',
            type=int, default=-1)
    parser.add_argument('--sharedmultiview',
            help='Enable AdVanced Illumination mode',
            action='store_true')
    parser.add_argument('--viewinitckpt',
            help='Initialize independent views in sequence with given checkpoints. --eval must present if viewinitckpt is given',
            nargs='*', default=[])
    parser.add_argument('--res',
            help='Resolution',
            type=int, default=config.DEFAULT_RES)
    parser.add_argument('--avi',
            help='Enable AdVanced Illumination mode',
            action='store_true')
    parser.add_argument('--viewset',
            help='Choose set of views',
            choices=['cube', '14', '22'],
            default='')
    parser.add_argument('--egreedy',
            help='Epsilon Greedy Policy',
            type=float,
            nargs='*',
            default=[0.2])
    parser.add_argument('--LAMBDA',
            help='Ratio between A2C loss and ICM loss. Note: ICM loss consists of loss from invert model and forward (curiosity) model',
            default=0.5)
    parser.add_argument('--GAMMA',
            help='Reward discount factor, negative value means lineay decay (cost)',
            type=float,
            default=config.GAMMA)
    parser.add_argument('--PEN',
            help='Penalty reward from collision',
            type=float,
            default=-10.0)
    parser.add_argument('--EXPLICIT_BATCH_SIZE',
            help='Penalty reward from collision',
            type=int,
            default=-1)
    parser.add_argument('--REW',
            help='Reward from disentanglement',
            type=float,
            default=10.0)
    parser.add_argument('--sancheck',
            help='Different sanity check points',
            type=int,
            nargs='*',
            default=[])
    parser.add_argument('--visionformula',
            help='Load preset formulas for vision. Note this overrides other options',
            type=int,
            choices=[1,2,3],
            default=0)
    parser.add_argument('--agents',
            metavar='NUMBER',
            help='Use multiple agents PER-THREAD to generalize the model',
            type=int,
            default=-1)
    parser.add_argument('--permutemag',
            metavar='REAL',
            help='Magnitude of translation in the randomized permutation',
            type=float,
            default=0.0)
    parser.add_argument('--manual_p',
            metavar='REAL NUMBER',
            nargs=7,
            help='Specify a fixed permutation',
            type=float,
            default=None)
    parser.add_argument('--jointfw',
            help='Use the joint all views as the input of forward model',
            action='store_true')
    parser.add_argument('--curiosity_type',
            help='Select type of curiosity. 1: Curiosity from mean squared error of feature vectors; 2: Curiosity from the squared for ratios',
            type=int,
            choices=[0,1,2],
            default=1)
    parser.add_argument('--curiosity_factor', help='Scaling factor of the returned curiosity',
            type=float,
            default=1.0)
    parser.add_argument('--qlearning_with_gt',
            help='Train the ValNet with Ground Truth from RRT, implies --train QwithGT',
            action='store_true')
    parser.add_argument('--qlearning_gt_file',
            metavar='FILE',
            help='Specify the Ground Truth File. This option enables qlearning_with_gt',
            default='')
    parser.add_argument('--exploredir',
            help='Path to store the exploration records',
            default=None)
    parser.add_argument('--visualize',
            help='''
Choose which aspect of the RL system to visualize.
policy: visualize the path walked by according to policy network.
curiosity: sample the curiosity value, i.e. forward model loss.
fake3d: sample Pi and V for fake3d cases
            ''',
            choices=['policy', 'curiosity', 'fake3d', 'critic', 'msa', 'caction', 'caction_sancheck', 'caction2'],
            default='policy')
    parser.add_argument('--msiraw',
            help='MileStone Injection (RAW state). in the same protocol as of --istateraw',
            type=float,
            nargs='*',
            default=[])
    parser.add_argument('--msi_file',
            help='MileStone Injection From File (unit state). Assumes the --sampleout file from --visualize msa',
            default='')
    parser.add_argument('--debug_flags',
            choices=['zero_weights'],
            nargs='*',
            default=[])
    parser.add_argument('--train',
            help='''
Choose which component to train separately (if --eval does not present).
a2c: whole system;
QwithGT: only Q function;
curiosity: train the forward model, expecting overfitting.
QandFCFE: Q and Fully Connected Layers in Feature Extractors.
q_overfit: train ValNet from scratch (i.e. w/o pretrained vision),
InF: Train Inverse model and Forward model with samples from files.
Ionly: Inverse model only.
a2c_overfit: Try to overfit the RL model with Actor-Critic Method.
dqn: Deep Q Network.
dqn_overfit: overfit DQN from scratch.
loco_overfit: overfit simplified deeploco (continuous action) from scratch
''',
            choices=['a2c', 'QwithGT', 'curiosity', 'QandFCFE', 'q_overfit', 'InF', 'Ionly',
                     'a2c_overfit', 'a2c_overfit_qonly', 'a2c_no_critic', 'a2c_abs_critic',
                     'a2c_overfit_from_fv', 'dqn', 'dqn_overfit', 'loco_overfit'],
            default='a2c')
    parser.add_argument('--notrain',
            help='Set untrainnable segments',
            choices=['fe'],
            nargs='*',
            default=[])
    # Distributed Tensorflow
    # (Maximize Performance under GIL)
    parser.add_argument('--localcluster_nsampler', metavar='NUMBER',
            help='Enable MP training by specifying the number of sampler processes',
            type=int, default=0)
    parser.add_argument('--localcluster_portbase', metavar='NUMBER',
            help='Port of the first worker process',
            type=int, default=0)
    parser.add_argument('--ps_hosts', metavar='HOST:PORT',
            nargs='*',
            help='(NOT RECOMMENDED) MANUALLY specify parameter server host(s)',
            default=[])
    parser.add_argument('--worker_hosts', metavar='HOST:PORT',
            nargs='*',
            help='(NOT RECOMMENDED) MANUALLY specify worker host(s)',
            default=[])
    """
    parser.add_argument('--task_index', metavar='NUMBER',
            help='Task index in distributed training',
            type=int, default=0)
    """

    return parser

def parse():
    parser = get_parser()
    args = parser.parse_args()
    if args.visionformula in [1,2,3]:
        args.elu = True
        args.res = 224
        args.avi = True
        args.ferev = 11
        args.viewset = 'cube'
        args.sharedmultiview = True
        args.featnum = 256
        args.imhidden = [256, 256]
        args.fehidden = [1024, 1024]
    if args.visionformula == 2:
        args.batchnorm = True
    if args.visionformula == 3:
        args.avi = False
    if args.qlearning_gt_file:
        args.qlearning_with_gt = True
    if args.train == 'QwithGT' or args.train == 'QandFCFE':
        args.qlearning_with_gt = True
    elif args.qlearning_with_gt:
        assert '--train' not in sys.argv, '--qlearning_with_gt overrides --train options'
        args.train = 'QwithGT'
    if -1 in args.actionset or len(args.actionset) == 0:
        args.actionset = [i for i in range(12)]
    if args.ckptdir is not None:
        assert args.ckptdir.endswith('/'), '--ckptdir should specify a directory rather a prefix'
    args.actionset = list(set(args.actionset)) # deduplication
    assert not (args.lstm and args.ereplayratio > 0), "LSTM cannot be used in combination with Experience Replay"
    assert len(args.msiraw) % 7 == 0, "--msiraw only accepts 7n elements as (R^3,W-First Quaternion)"
    if args.localcluster_nsampler > 0:
        assert args.localcluster_portbase != 0, "--localcluster_portbase is missing"
    return args
