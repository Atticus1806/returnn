
# start test like this:  nosetests-2.7  tests/test_TFNativeOp.py  --nologcapture


import logging
logging.getLogger('tensorflow').disabled = True
import tensorflow as tf
import sys
sys.path += ["."]  # Python 3 hack
from TFNativeOp import *
from TFUtil import is_gpu_available, CudaEnv
import Util
import unittest
from nose.tools import assert_equal, assert_is_instance
import numpy
import numpy.testing
from numpy.testing.utils import assert_almost_equal
import os
import better_exchook
better_exchook.replace_traceback_format_tb()


CudaEnv.verbose_find_cuda = True
session = tf.InteractiveSession()


def dump_info():
  numpy_path = os.path.dirname(numpy.__file__)
  print("Numpy path: %r" % numpy_path)
  so_files = Util.sysexecOut("find %s | grep \"\.so\"" % numpy_path, shell=True)
  print("Numpy so files:\n---\n%s\n---\n" % so_files)
  so_files = [f for f in so_files.splitlines() if f]
  ldd = "ldd"
  if sys.platform == "darwin":
    ldd = "otool -L"
  objdump = "objdump -T"
  if sys.platform == "darwin":
    objdump = "otool -IHGv"
  for f in so_files:
    cmd = "%s %s" % (ldd, f)
    print("$ %s" % cmd)
    out = Util.sysexecOut(cmd, shell=True)
    print(out)
    cmd = "%s %s | { grep sgemm || true; }" % (objdump, f)
    print("$ %s" % cmd)
    out = Util.sysexecOut(cmd, shell=True)
    print(out)


def test_dummy():
  dump_info()
  #assert False


def test_make_lstm_op_auto_cuda():
  try:
    make_lstm_op()
  except tf.errors.NotFoundError:
    dump_info()
    raise


def test_make_lstm_op_no_cuda():
  try:
    OpMaker.with_cuda = False
    make_lstm_op()
  except tf.errors.NotFoundError:
    dump_info()
    raise
  finally:
    OpMaker.with_cuda = None


def test_NativeLstmCell():
  n_time = 2
  n_batch = 1
  n_hidden = 3
  cell = NativeLstmCell(n_hidden)
  inputs = tf.zeros([n_time, n_batch, n_hidden * 4])
  index = tf.ones([n_time, n_batch])
  outputs, final_state = cell(inputs, index)


@unittest.skipIf(not is_gpu_available(), "no gpu on this system")
def test_FastBaumWelch():
  print("Make op...")
  op = make_fast_baum_welch_op(compiler_opts=dict(verbose=True))  # will be cached, used inside :func:`fast_baum_welch`
  print("Op:", op)
  n_batch = 3
  seq_len = 5
  n_classes = 10
  from Fsa import FastBwFsaShared
  fsa = FastBwFsaShared()
  fsa.add_inf_loop(state_idx=0, num_emission_labels=n_classes)
  fast_bw_fsa = fsa.get_fast_bw_fsa(n_batch=n_batch)
  edges = tf.constant(fast_bw_fsa.edges, dtype=tf.int32)
  weights = tf.constant(fast_bw_fsa.weights, dtype=tf.float32)
  start_end_states = tf.constant(fast_bw_fsa.start_end_states, dtype=tf.int32)
  am_scores = tf.constant(numpy.random.normal(size=(seq_len, n_batch, n_classes)), dtype=tf.float32)  # in -log space
  float_idx = tf.ones((seq_len, n_batch), dtype=tf.float32)
  print("Construct call...")
  fwdbwd, obs_scores = fast_baum_welch(
    am_scores=am_scores, float_idx=float_idx,
    edges=edges, weights=weights, start_end_states=start_end_states)
  print("Done.")
  print("Eval:")
  _, score = session.run([fwdbwd, obs_scores])
  print("score:", score)


@unittest.skipIf(not is_gpu_available(), "no gpu on this system")
def test_fast_bw_uniform():
  print("Make op...")
  op = make_fast_baum_welch_op(compiler_opts=dict(verbose=True))  # will be cached, used inside :func:`fast_baum_welch`
  # args: (am_scores, edges, weights, start_end_states, float_idx, state_buffer)
  print("Op:", op)
  n_batch = 3
  seq_len = 10
  n_classes = 5
  from Fsa import FastBwFsaShared
  fsa = FastBwFsaShared()
  for i in range(n_classes):
    fsa.add_edge(i, i + 1, emission_idx=i)  # fwd
    fsa.add_edge(i + 1, i + 1, emission_idx=i)  # loop
  assert n_classes <= seq_len
  fast_bw_fsa = fsa.get_fast_bw_fsa(n_batch=n_batch)
  edges = tf.constant(fast_bw_fsa.edges, dtype=tf.int32)
  weights = tf.constant(fast_bw_fsa.weights, dtype=tf.float32)
  start_end_states = tf.constant(fast_bw_fsa.start_end_states, dtype=tf.int32)
  am_scores = tf.constant(numpy.random.normal(size=(seq_len, n_batch, n_classes)), dtype=tf.float32)  # in -log space
  float_idx = tf.ones((seq_len, n_batch), dtype=tf.float32)
  print("Construct call...")
  fwdbwd, obs_scores = fast_baum_welch(
    am_scores=am_scores, float_idx=float_idx,
    edges=edges, weights=weights, start_end_states=start_end_states)
  print("Done.")
  print("Eval:")
  fwdbwd, score = session.run([fwdbwd, obs_scores])
  print("score:", score)  # seems wrong? Theano returns: [[ 3.65274048  3.65274048  3.65274048] ...]
  bw = numpy.exp(-fwdbwd)
  print("Baum-Welch soft alignment:")
  print(bw)
  assert_equal(bw.shape, (seq_len, n_batch, n_classes))
  if seq_len == n_classes:
    print("Extra check...")
    for i in range(n_batch):
      assert_almost_equal(numpy.identity(n_classes), bw[:, i])
  print("Done.")


if __name__ == "__main__":
  try:
    better_exchook.install()
    if len(sys.argv) <= 1:
      for k, v in sorted(globals().items()):
        if k.startswith("test_"):
          print("-" * 40)
          print("Executing: %s" % k)
          v()
          print("-" * 40)
    else:
      assert len(sys.argv) >= 2
      for arg in sys.argv[1:]:
        print("Executing: %s" % arg)
        if arg in globals():
          globals()[arg]()  # assume function and execute
        else:
          eval(arg)  # assume Python code and execute
  finally:
    session.close()
    del session
    tf.reset_default_graph()
    import threading
    if len(list(threading.enumerate())) > 1:
      print("Warning, more than one thread at exit:")
      better_exchook.dump_all_thread_tracebacks()
