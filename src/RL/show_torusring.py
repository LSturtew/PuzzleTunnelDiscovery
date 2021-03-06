# SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
# SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
# SPDX-License-Identifier: GPL-2.0-or-later
import pyosr
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from PIL import Image
from scipy.misc import imsave
import vision
import tensorflow as tf
import rldriver
import config
import threading
import time
import util
from rmsprop_applier import RMSPropApplier
from datetime import datetime

class _LoggerHook(tf.train.SessionRunHook):
    """Logs loss and runtime."""

    def __init__(self, loss):
        self.loss = loss

    def begin(self):
          self._step = -1

    def before_run(self, run_context):
        self._step += 1
        self._start_time = time.time()
        return tf.train.SessionRunArgs(self.loss)  # Asks for loss value.

    def after_run(self, run_context, run_values):
        duration = time.time() - self._start_time
        loss_value = run_values.results
        if self._step % 10 == 0:
            num_examples_per_step = config.BATCH_SIZE
            examples_per_sec = num_examples_per_step / duration
            sec_per_batch = float(duration)

            format_str = ('%s: step %d, loss = %.2f (%.1f examples/sec; %.3f '
                    'sec/batch)')
            print (format_str % (datetime.now(), self._step, loss_value,
                examples_per_sec, sec_per_batch))

RMSP_ALPHA = 0.99 # decay parameter for RMSProp
RMSP_EPSILON = 0.1 # epsilon parameter for RMSProp
GRAD_NORM_CLIP = 40.0 # gradient norm clipping
device = "/cpu:0"
MODELS = ['../res/simple/FullTorus.obj', '../res/simple/robot.obj']
init_state = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
view_config = [(30.0, 12), (-30.0, 12), (0, 4), (90, 1), (-90, 1)]
ckpt_dir = './ttorus/ckpt-mt-6'
# ckpt_dir = './ttorus/ckpt-guided'

def show_torus_ring():
    pyosr.init()
    dpy = pyosr.create_display()
    glctx = pyosr.create_gl_context(dpy)
    g = tf.Graph()
    util.mkdir_p(ckpt_dir)
    with g.as_default():
        learning_rate_input = tf.placeholder(tf.float32)
        grad_applier = RMSPropApplier(learning_rate=learning_rate_input,
                                      decay=RMSP_ALPHA,
                                      momentum=0.0,
                                      epsilon=RMSP_EPSILON,
                                      clip_norm=GRAD_NORM_CLIP,
                                      device=device)
        masterdriver = rldriver.RLDriver(MODELS,
                init_state,
                view_config,
                config.SV_VISCFG,
                config.MV_VISCFG,
                use_rgb=True)
        global_step = tf.contrib.framework.get_or_create_global_step()
        increment_global_step = tf.assign_add(global_step, 1, name='increment_global_step')
        saver = tf.train.Saver(masterdriver.get_nn_args() + [global_step])
        last_time = time.time()
        with tf.Session() as sess:
            sess.run(tf.global_variables_initializer())
            ckpt = tf.train.get_checkpoint_state(checkpoint_dir=ckpt_dir)
            print('ckpt {}'.format(ckpt))
            epoch = 0
            policy_before, value_before, _, _ = masterdriver.evaluate(sess)
            #print("Last b before {}".format(sess.run(masterdriver.get_nn_args()[-2])))
            if ckpt and ckpt.model_checkpoint_path:
                saver.restore(sess, ckpt.model_checkpoint_path)
                epoch = sess.run(global_step)
                print('Restored!, global_step {}'.format(epoch))
            else:
                print('Cannot find checkpoint at {}'.format(ckpt_dir))
                return
            policy_after, value_after, _, _ = masterdriver.evaluate(sess)
            print("Value Before Restoring {} and After {}".format(value_before, value_after))
            # print("Last b {}".format(sess.run(masterdriver.get_nn_args()[-2])))
            driver = masterdriver
            r = masterdriver.renderer
            fig = plt.figure()
            class ReAnimator(object):
                reaching_terminal = False
                driver = None
                im = None
                sess = None

                def __init__(self, driver, sess):
                    self.driver = driver
                    self.sess = sess

                def perform(self, framedata):
                    driver = self.driver
                    r = driver.renderer
                    sess = self.sess
                    if not self.reaching_terminal:
                        policy, value, img, dep = driver.evaluate(sess)
                        policy = policy.reshape(driver.action_size)
                        action = driver.make_decision(policy, sess)
                        nstate,reward,self.reaching_terminal = driver.get_reward(action)
                        valid = r.is_valid_state(nstate)
                        print('Current Value {} Policy {} Action {} Reward {}'.format(value, policy, action, reward))
                        print('\tNew State {} Collision Free ? {}'.format(nstate, valid))
                        # print('Action {}, New State {}'.format(action, nstate))
                        rgb = np.squeeze(img[0, 0, :, : ,:], axis=[0,1])
                        if self.im is None:
                            print('rgb {}'.format(rgb.shape))
                            self.im = plt.imshow(rgb)
                        else:
                            self.im.set_array(rgb)
                        r.state = nstate
            ra = ReAnimator(driver, sess)
            ani = animation.FuncAnimation(fig, ra.perform)
            plt.show()

if __name__ == '__main__':
    show_torus_ring()
