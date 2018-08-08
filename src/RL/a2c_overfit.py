from __future__ import print_function
from a2c import A2CTrainer
import tensorflow as tf
import rlenv
import numpy as np
import rlutil

class OverfitTrainer(A2CTrainer):
    def __init__(self,
            advcore,
            tmax,
            gamma,
            learning_rate,
            ckpt_dir,
            global_step=None,
            entropy_beta=0.01,
            debug=True,
            batch_normalization=None,
            period=1,
            total_number_of_replicas=None,
            LAMBDA=0.5,
            train_everything=False
            ):
        super(OverfitTrainer, self).__init__(
                advcore=advcore,
                tmax=tmax,
                gamma=gamma,
                learning_rate=learning_rate,
                ckpt_dir=ckpt_dir,
                global_step=global_step,
                entropy_beta=entropy_beta,
                debug=debug,
                batch_normalization=batch_normalization,
                period=period,
                total_number_of_replicas=total_number_of_replicas,
                LAMBDA=LAMBDA,
                train_everything=train_everything)
        self.all_samples_cache = []
        self.minibatch_index = 0
        self.num_actions = len(advcore.args.actionset)

    # Redefine actor critic function, details:
    # 1. We are trying to overfit the model through a known optimal path
    # 2. Hence we can't calculate V* since Monte Carlo part was removed
    # 3. Therefore we can assume every other trajectory yields 0 long term rewards
    # 4. Thus, V* = V_{opt} times 1/total number of actions ^ (remaining length of this trajectory),
    #    since at each step, the probability to take the optimal action is 1/total number of actions
    # This requires a different loss function and different set of inputs
    def build_loss(self, advcore):
        if self.loss is not None:
            return self.loss
        self.Adist_tensor = advcore.action_tensor
        # TD is required
        # V_sample - V*, for this case it's V_opt - V*
        self.V_star = tf.placeholder(tf.float32, shape=[None], name='V_star_ph')
        self.V_tensor = tf.placeholder(tf.float32, shape=[None], name='VPh')

        flattened_value = tf.reshape(advcore.value, [-1])
        policy = tf.multiply(advcore.softmax_policy, self.Adist_tensor)
        policy = tf.reduce_sum(policy, axis=[1,2])
        log_policy = tf.log(tf.clip_by_value(policy, 1e-20, 1.0))
        policy_per_sample = log_policy * tf.stop_gradient(self.V_tensor - flattened_value)
        criticism = self.V_tensor - flattened_value
        policy_loss = tf.reduce_sum(-policy_per_sample)
        value_loss = tf.nn.l2_loss(self.V_star - flattened_value)

        self.loss = policy_loss + value_loss
        return self.loss

    def train(self, envir, sess, tid=None, tmax=-1):
        advcore = self.advcore
        if not self.all_samples_cache:
            print("Caching samples")
            while True:
                rlsamples, final_state = self.sample_minibatch(envir, sess, tid, tmax)
                self.all_samples_cache.append((rlsamples, final_state))
                if rlsamples[-1].reaching_terminal:
                    break
        (rlsamples, final_state) = self.all_samples_cache[self.minibatch_index % len(self.all_samples_cache)]
        assert isinstance(rlsamples[0], rlenv.RLSample), "rlsamples[0] is not RLSample"
        assert isinstance(final_state, rlenv.RLSample), "final_state is not RLSample"
        self.minibatch_index += 1 # [DISABLED] HACKING: NO SECOND SEGMENT

        # Collect image and action input
        vstates = [s.vstate for s in rlsamples] + [final_state.vstate]
        # print('{}'.format(rlsamples[0].vstate[0].shape))
        batch_rgb = [state[0] for state in vstates]
        batch_dep = [state[1] for state in vstates]
        action_indices=[s.action_index for s in rlsamples]
        batch_adist = rlutil.actions_to_adist_array(action_indices, dim=self.action_space_dimension)

        # Collect V* and V
        if final_state.is_terminal:
            V = 0.0
        else:
            V = np.asscalar(advcore.evaluate([final_state.vstate], sess, tensors=[advcore.value])[0])
        V_star = V

        r_rewards = [s.combined_reward for s in rlsamples][::-1]
        batch_V = []
        batch_V_star = []
        GAMMA = self.gamma
        KAPPA = 1.0 / self.num_actions
        assert GAMMA > 0, "a2c_overfit does not support linear decay"
        for r in r_rewards:
            V = r + GAMMA * V
            # Programmatically batch_V_star = batch_V * KAPPA
            # We did this to elaborate the derivation of V_star
            V_star = KAPPA * r + KAPPA * GAMMA * V
            batch_V.append(V)
            batch_V_star.append(V_star)
        batch_V.reverse()
        batch_V_star.reverse()

        ndic = {
                'rgb' : batch_rgb,
                'dep' : batch_dep,
                'aindex' : action_indices,
                'adist' : batch_adist,
                'V' : batch_V,
                'Vstar' : batch_V_star,
               }
        self.dispatch_training(sess, ndic)

    def dispatch_training(self, sess, ndic, debug_output=True):
        advcore = self.advcore
        dic = {
                advcore.rgb_1: ndic['rgb'][:-1],
                advcore.dep_1: ndic['dep'][:-1],
                advcore.rgb_2: ndic['rgb'][1:],
                advcore.dep_2: ndic['dep'][1:],
                advcore.action_tensor : ndic['adist'],
                self.V_star : ndic['Vstar'],
                self.V_tensor: ndic['V']
              }
        if self.summary_op is not None:
            _, summary, gs = sess.run([self.train_op, self.summary_op, self.global_step], feed_dict=dic)
            self.train_writer.add_summary(summary, gs)
        else:
            sess.run(self.train_op, feed_dict=dic)

'''
Try to overfit V and P with given samples
'''
class OverfitTrainerFromFV(object):
    def __init__(self,
            advcore,
            tmax,
            gamma,
            learning_rate,
            ckpt_dir,
            global_step=None,
            entropy_beta=0.01,
            debug=True,
            batch_normalization=None,
            period=1,
            total_number_of_replicas=None,
            LAMBDA=0.5,
            train_everything=False
            ):
        pass