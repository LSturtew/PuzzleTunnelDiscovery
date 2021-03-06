# SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
# SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
# SPDX-License-Identifier: GPL-2.0-or-later
'''
Overall design idea:
    separate the TF inferencing network, training network, rendering, and TF session
    - Inferencing network is managed by IAdvantageCore
    - training network is managed by trainer classes (e.g. A2CTrainer)
    - rendering is moved to IEnvironment
    - TF session is provided by trainer class
'''

from abc import ABCMeta, abstractmethod, abstractproperty
import tensorflow as tf
from collections import deque
import itertools
import random
import numpy as np
import copy

'''
Note: Python2 code?
'''

'''
IEnvironment: Interface to objects that describe the RL environment
'''
class IEnvironment(object):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(IEnvironment, self).__init__()
        self.lstm_barn = None

    '''
    Property for Configuration(Q) state
    RW
    '''
    @abstractmethod
    def qstate_setter(self, state):
        pass

    @abstractmethod
    def qstate_getter(self):
        pass

    qstate = abstractproperty(qstate_getter, qstate_setter)

    @abstractmethod
    def get_perturbation(self):
        pass

    '''
    Property for Viewable state (i.e. RGB-D images)
    RO, should return [rgb,dep]
    '''
    @abstractproperty
    def vstate(self):
        pass

    '''
    Property for Viewable state (i.e. RGB-D images) dimension
    RO, should return [view,w,h]
    '''
    @abstractproperty
    def vstatedim(self):
        pass

    '''
    Return [new_state, reward, reaching_terminal]
    Note:
        1. do not actually perform the action -- use qstate setter to do this
        2. artificial reward is in IAdvantageCore
    '''
    @abstractmethod
    def peek_act(self, action):
        pass

    '''
    Reset to initial state
    '''
    @abstractmethod
    def reset(self):
        pass

'''
IExperienceReplayEnvironment:
    Interface to objects that not only describe the RL environment, but also records the experiences

    Note: this experience recording can be disabled by passing negative numbers to erep_cap when creating
'''
class IExperienceReplayEnvironment(IEnvironment):

    def __init__(self, tmax, erep_cap, dumpdir=None):
        super(IExperienceReplayEnvironment, self).__init__()
        assert not (erep_cap > 0 and dumpdir is not None), "--ereplayratio is incompatitable with --exploredir in current implementation"
        self.tmax = tmax
        self.erep_sample_cap = erep_cap * tmax
        self.erep_vstates = deque()
        self.erep_qstates = deque()
        self.erep_actions = deque()
        self.erep_ratios = deque()
        self.erep_reward = deque()
        self.erep_term = deque()
        self.erep_perm = deque()
        self.erep_all_deques = (self.erep_vstates, self.erep_qstates, self.erep_actions,
                self.erep_ratios,
                self.erep_reward, self.erep_term,
                self.erep_perm
                )
        '''
        State Action raTio Reward Queues, for Sampling
        '''
        self.erep_satr_deques = (self.erep_vstates, self.erep_actions,
                self.erep_ratios, self.erep_reward)
        self.dumpdir = dumpdir
        self.dump_id = 0

    '''
    Store Experience REPlay
    '''
    def store_erep(self, vstate, qstate, action, ratio, reward, reaching_terminal, perm):
        if self.erep_sample_cap <= 0 and self.dumpdir is None:
            return
        self.erep_vstates.append(vstate)
        self.erep_qstates.append(qstate)
        self.erep_actions.append(action)
        self.erep_ratios.append(ratio)
        self.erep_reward.append(reward)
        self.erep_term.append(reaching_terminal)
        self.erep_perm.append(perm)
        if self.erep_sample_cap > 0:
            while len(self.erep_actions) > self.erep_sample_cap:
                [q.popleft() for q in self.erep_all_deques]
        elif self.dumpdir is not None:
            if len(self.erep_actions) > 128:
                fn = '{}/{}.npz'.format(self.dumpdir, self.dump_id)
                np.savez(fn, QSTATE=list(self.erep_qstates),
                        A=list(self.erep_actions),
                        TAU=list(self.erep_ratios),
                        R=list(self.erep_reward),
                        T=list(self.erep_term),
                        PERM=list(self.erep_perm)
                        )
                [q.clear() for q in self.erep_all_deques]
                self.dump_id += 1

    def sample_in_erep(self, pprefix):
        if self.erep_sample_cap <= 0:
            return [],[],[],[],False
        # FIXME: Handle terminal in the cache
        cached_samples = len(self.erep_actions)
        size = min(cached_samples, self.tmax)
        start = random.randrange(-size + 1, cached_samples)
        pick_start = max(start, 0)
        pick_end = min(start + size, cached_samples)
        s,a,t,r = (list(itertools.islice(q, pick_start, pick_end)) for q in self.erep_satr_deques)
        '''
        Number of actions = Number of States - 1
        So the last element of ATR was trimmed
        Otherwise we have no final state after the last action
        '''
        a=a[:-1]
        t=t[:-1]
        r=r[:-1]
        if len(a) > 0:
            assert a[-1] >= 0 and self.erep_term[pick_end-1] == False, "State without valid action was picked up"
        return s,a,t,r,self.erep_term[pick_end-1]

    def reset(self):
        [q.clear() for q in self.erep_all_deques]

'''
IAdvantageCore:
    Interface to objects that provides deep inferencing network
'''
class IAdvantageCore(object):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(IAdvantageCore, self).__init__()
        self._softmax_policy_tensor = None
        self.curiosity_params = None
        self.ratios_tensor = None

    '''
    Input RGB for Current Frame
    RO, placeholder
    '''
    @abstractproperty
    def rgb_1(self):
        pass

    '''
    Input RGB for Next Frame
    RO, placeholder
    '''
    @abstractproperty
    def rgb_2(self):
        pass

    '''
    Input Depth for Current Frame
    RO, placeholder
    '''
    @abstractproperty
    def dep_1(self):
        pass

    '''
    Input Depth for Next Frame
    RO, placeholder
    '''
    @abstractproperty
    def dep_2(self):
        pass

    '''
    Policy tensor (action distribution) before softmax
    Input placeholders are rgb_1 and dep_1

    RO, tensor
    '''
    @abstractproperty
    def policy(self):
        pass

    @property
    def softmax_policy(self):
        if self._softmax_policy_tensor is None:
            self._softmax_policy_tensor = tf.nn.softmax(logits=self.policy)
        return self._softmax_policy_tensor

    '''
    Value tensor (Q function value)
    Input placeholders are rgb_1 and dep_1

    RO, tensor
    '''
    @abstractproperty
    def value(self):
        pass

    '''
    NN Params of Policy Net
    RO, list of tf.Variable
    '''
    @abstractproperty
    def policy_params(self):
        pass

    '''
    NN Params of Value Net
    RO, list of tf.Variable
    '''
    @abstractproperty
    def value_params(self):
        pass

    '''
    Evaluate the environment
    vstates: List of vstate from IEnvironment
    '''
    @abstractmethod
    def evaluate(self, vstates, sess, tensors, additional_dict=None):
        pass

    '''
    Return the index of decided action from a policy distribution
    Note: due to the interface of cross entropy loss,
          the input was not filtered by softmax
    Note2: we need envir because we want to store agent specific data to envir
    '''
    @abstractmethod
    def make_decision(self, envir, policy_dist):
        pass

    '''
    Return the artificial reward
    '''
    @abstractmethod
    def get_artificial_reward(self, envir, sess, state_1, action, state_2, ratio, pprefix):
        pass

    '''
    Return the artificial reward
    '''
    @abstractmethod
    def get_artificial_from_experience(self, sess, vstates, actions, ratios):
        pass

    '''
    Train/Refine any embedded model

    Note: cannot be merged to a2c since ICM has different inputs
    Note2: actions should be a distribution

    CAVEAT: deprecated, use build_loss instead
    '''
    def train(self, sess, rgb, dep, actions):
        raise "Deprecated buggy solution"

    @abstractmethod
    def build_loss(self):
        '''
        Return the interal loss function from a segment
        '''
        pass

    '''
    Return the cached lstm state for the next state.
    '''
    @abstractproperty
    def lstm_next(self):
        pass

    @abstractmethod
    def set_lstm(self, lstm):
        pass

    @abstractmethod
    def get_lstm(self):
        pass


'''
One sample from the environment
'''
class RLSample(object):
    def __init__(self, advcore, envir, sess, is_terminal=False):
        # Capture Current Frame
        self.qstate = envir.qstate
        self.perturbation = envir.get_perturbation()
        self.vstate = envir.vstate
        self.is_terminal = is_terminal
        if is_terminal:
            self.policy = None
            self.value = 0.0
        elif advcore.args.train == 'dqn':
            # Note we need to use softmax_policy to eliminate unselected actions
            # We may have negative Q value so setting unselection actions to 0
            # in polout is not practical
            [policy] = advcore.evaluate([envir.vstate], sess, [advcore.softmax_policy])
            self.policy = policy[0][0] # first qstate and first view
        else:
            # Sample Pi and V
            policy, value = advcore.evaluate([envir.vstate], sess, [advcore.softmax_policy, advcore.value])
            self.policy = policy[0][0] # Policy View from first qstate and first view
            self.value = np.asscalar(value) # value[0][0][0]

    '''
        Side effects:
            1. envir.qstate is changed according to the evaluated policy function
            2. self.advcore.lstm_state is changed
    '''
    def proceed(self, advcore, envir, sess):
        # Sample Action
        self.action_index = advcore.make_decision(envir, self.policy)
        # Preview Next frame
        self.nstate, self.true_reward, self.reaching_terminal, self.ratio = envir.peek_act(self.action_index)
        # Artificial Reward
        self.artificial_reward = advcore.get_artificial_reward(envir, sess,
                envir.qstate, self.action_index, self.nstate, self.ratio)
        self.combined_reward = self.true_reward + self.artificial_reward
        # Side Effects: change qstate
        envir.qstate = self.nstate
        # Side Effects: Maintain LSTM
        lstm_next = copy.deepcopy(advcore.get_lstm()) # Get the output of current frame
        advcore.set_lstm(lstm_next) # AdvCore next frame

'''
Sample a trajectory, maybe incomplete
'''
class MiniBatchSampler(object):

    def __init__(self,
                 advcore,
                 tmax):
        self.advcore = advcore
        self.a2c_tmax = tmax

    '''
    Sample one in a mini-batch

    Side effects: self.advcore.lstm_state is changed
    '''
    def _sample_one(self, envir, sess):
        sam = RLSample(self.advcore, envir, sess)
        sam.proceed(self.advcore, envir, sess)
        return sam

    def sample_minibatch(self, envir, sess, tid=None, tmax=-1):
        if tmax < 0:
            tmax = self.a2c_tmax
        advcore = self.advcore
        samples = []
        # LSTM is also tracked by Envir, since it's derived by vstate
        # FIXME: Initialize envir.lstm_barn somewhere else.
        advcore.set_lstm(envir.lstm_barn)
        for i in range(tmax):
            s = self._sample_one(envir, sess)
            samples.append(s)
            if s.reaching_terminal:
                break
        reaching_terminal = samples[-1].reaching_terminal
        envir.lstm_barn = copy.deepcopy(advcore.get_lstm())
        final = RLSample(self.advcore, envir, sess, is_terminal=reaching_terminal)
        if reaching_terminal:
            envir.reset()
        return (samples, final)


'''
Sample a trajectory from given --msi_file
'''
class CachedMiniBatchSampler(MiniBatchSampler):

    def __init__(self,
                 advcore,
                 args):
        assert args.msi_file, "CachedMiniBatchSampler requires --msi_file"
        self.args = args
        super(CachedMiniBatchSampler, self).__init__(advcore, args.batch)
        self.all_samples_cache = []
        self.minibatch_index = 0

    def sample_minibatch(self, envir, sess, tid=None, tmax=-1):
        if not self.all_samples_cache:
            while True:
                rlsamples, final_state = super(CachedMiniBatchSampler, self).sample_minibatch(envir, sess, tid, tmax)
                self.all_samples_cache.append((rlsamples, final_state))
                if rlsamples[-1].reaching_terminal:
                    break
            if self.args.EXPLICIT_BATCH_SIZE == 1:
                # Attach exp. value to each rlsample
                all_rewards = [s[0].combined_reward for (s,f) in self.all_samples_cache]
                eV = 0.0
                all_ev = [eV]
                for r in all_rewards[::-1]:
                    eV = r + GAMMA * eV
                    all_ev.append(eV)
                all_ev.reverse()
                all_fs = [f for (s,f) in self.all_samples_cache]
                assert len(all_ev) - 1 == len(all_fs), "size mismatch {} {}".format(len(all_ev), len(all_fs))
                for eV,fs in zip(all_ev[1:], all_fs):
                    fs.exp_value = eV
        (rlsamples, final_state) = self.all_samples_cache[self.minibatch_index % len(self.all_samples_cache)]
        assert isinstance(rlsamples[0], RLSample), "rlsamples[0] is not RLSample"
        assert isinstance(final_state, RLSample), "final_state is not RLSample"

        self.minibatch_index = (self.minibatch_index + 1) % len(self.all_samples_cache)
        return (rlsamples, final_state)

'''
Sample a trajectory ending with non-zero rewards
'''
class WholeTrajSampler(MiniBatchSampler):
    def __init__(self,
                 advcore):
        super(WholeTrajSampler, self).__init__(advcore=advcore, tmax=-1)

    def sample_minibatch(self, envir, sess, tid=None, tmax=-1):
        advcore = self.advcore
        samples = []
        while True:
            s = self._sample_one(envir, sess)
            samples.append(s)
            if s.true_reward != 0:
                break
        final = RLSample(self.advcore, envir, sess, is_terminal=True)
        if 'die' in advcore.args.gameconf:
            envir.reset()
        return (samples, final)
