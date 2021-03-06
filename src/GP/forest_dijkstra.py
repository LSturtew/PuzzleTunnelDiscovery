#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
# SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
# SPDX-License-Identifier: GPL-2.0-or-later

'''
Solve the SSSP problem in forest, with NetworkX
'''

import sys, os
sys.path.append(os.getcwd())

import argparse
import numpy as np
from scipy.io import loadmat,savemat
import scipy.sparse as sparse
from progressbar import progressbar
import itertools
import os
import networkx as nx
from pipeline import matio

VIRTUAL_OPEN_SPACE_NODE = 1j

def _lsv(indir, prefix, suffix):
    ret = []
    for i in itertools.count(0):
        fn = "{}/{}{}{}".format(indir, prefix, i, suffix)
        if not os.path.exists(fn):
            if not ret:
                raise FileNotFoundError("Cannot even locate the a single file under {}. Complete path: {}".format(indir, fn))
            return ret
        ret.append(fn)

def _load(fefn, ds_name='E'):
    d = matio.load(fefn)
    return d[ds_name] if ds_name in d else None

class TreePathFinder(object):
    def __init__(self, root, ssc_fn, ct_fn, pds, pds_ids, pds_flags, bloom_range, bloom_fn):
        print("Loading data from {} {}".format(ssc_fn, ct_fn))
        self._root_conf = root
        self._ssc = loadmat(ssc_fn)['C'] # Note: no flatten for sparse matrix
        d = loadmat(ct_fn)
        self._ct_fn = ct_fn
        self._ct_nouveau_indices = d['CNVI'].flatten() # In case it's stored as 1xN or Nx1 matrix
        self._ct_nouveau_vertices = d['CNV']
        self._ct_edges = d['CE']
        self._pds = pds
        self._pds_flags = pds_flags
        self._bloom_range = bloom_range
        self._bloom_fn = bloom_fn
        G = self._G = nx.Graph()
        G.add_nodes_from([-1]) # One root
        G.add_nodes_from(pds_ids)
        # print(self._ct_edges[:20])
        G.add_edges_from(self._ct_edges)

        self._bloom_G = None

    def get_node_conf(self, node):
        if node < 0:
            assert node == -1, 'Only support single initial state'
            return self._root_conf
        # print("node {}".format(node))
        # print("ssc shape {}".format(self._ssc.shape))
        if self._ssc[0, node] != 0:
            # This is a PDS node
            return self._pds[node]
        # Not PDS, need to lookup the nouveau indices
        nouveau_index = np.where(self._ct_nouveau_indices==node)[0][0]
        return self._ct_nouveau_vertices[nouveau_index]

    def nodelist_from_root(self, leaf):
        PDS_FLAG_TERMINATE = 1 # FIXME: deduplicate this definition
        print("Finding path from root to {} within {}".format(leaf, self._ct_fn))
        if isinstance(leaf, complex):
            # Substitute VIRTUAL_OPEN_SPACE_NODE with the actual node in the open space
            assert leaf == VIRTUAL_OPEN_SPACE_NODE
            assert self._pds_flags is not None
            directly_connected = self._ssc.nonzero()[1]
            for n in directly_connected:
                if (self._pds_flags[n] & PDS_FLAG_TERMINATE) != 0:
                    print("Substitute leaf {} with {}".format(leaf, n))
                    leaf = n
                    # print('CT edges\n{}'.format(self._ct_edges))
                    break
        if self.has_edge_to_pds(leaf):
            return self.bloom_nodes_from_root(leaf)
        assert self._ssc[0, leaf] != 0
        # compact tree uses -1 as the root, and 0,1,2,... are PDS nodes
        ids = nx.shortest_path(self._G, -1, leaf)
        print("IDs on the path {}".format(ids))
        ssc_on_path = []
        for i in ids:
            if i < 0:
                ssc_on_path.append('ROOT')
            else:
                ssc_on_path.append(self._ssc[0,i])
        print("SSC on the path {}".format(ssc_on_path))
        path = [self.get_node_conf(node) for node in ids]
        return path[::-1]

    def has_edge_to_pds(self, pds_id):
        if self._bloom_range is None or self._bloom_fn is None:
            return False
        f, t = self._bloom_range
        return f <= pds_id < t

    def bloom_nodes_from_root(self, pds_id):
        d = matio.load(self._bloom_fn)
        if self._bloom_G is None:
            G = self._bloom_G = nx.Graph()
            self._bloom_nodes = d['BLOOM']
            n = self._bloom_nodes.shape[0]
            bloom_edges = np.transpose(d['BLOOM_EDGE'])
            G.add_nodes_from([i for i in range(n)])
            G.add_edges_from(bloom_edges)
        G = self._bloom_G
        f, t = self._bloom_range
        leaf = pds_id - f
        print("Finding path from root to {} (pds_id {}) within {}".format(leaf, pds_id, self._bloom_fn))
        # bloom tree uses 0 as the root
        bloom_roots = d['IS_INDICES']
        assert bloom_roots.size == 1
        ids = nx.shortest_path(self._G, int(bloom_roots[0]), leaf)
        print("BLOOM IDs on the path {}".format(ids))
        path = [self._bloom_nodes[node] for node in ids]
        return path[::-1]

class ForestPathFinder(object):
    def __init__(self, args):
        self._args = args
        self._probe_forest_data()
        self._cached_tree = None
        self._cached_tree_root = None

    def _probe_forest_data(self):
        print("Loading forest data")
        args = self._args
        #d = np.load(args.rootf)
        #self._roots = d[list(d.keys())[0]]
        self._roots = _load(args.rootf, ds_name='KEYQ_OMPL')
        self._ssc_files = _lsv(args.indir, args.prefix_ssc, '.mat')
        self._pds_size = loadmat(self._ssc_files[0])['C'].shape[1]
        self._pds_ids = [i for i in range(self._pds_size)]
        self._pds = _load(args.pdsf, 'Q')
        self._pds_flags = _load(args.pdsf, 'QF')
        self._ct_files = _lsv(args.indir, args.prefix_ct, '.mat')
        nssc = len(self._ssc_files)
        nct = len(self._ct_files)
        assert nssc == nct, 'number of compact tree files ({}) should match number of sample set connectivity files ({})'.format(nct, nssc)
        self._nroots = int(self._roots.shape[0])
        assert self._nroots == nct, 'number of roots ({}) should match number of sample set connectivity files ({})'.format(self._nroots, nssc)
        self._bloom_range = None
        self._bloom_files = None
        if args.bloom_dir is not None:
            QB = _load(args.rootf, 'QB') # Q (configuration) Base
            if QB is not None:
                eot = int(QB[-1])
                QB = QB.tolist()
                QB.append(eot)
                bloom_range = []
                for f, t in zip(QB[:-1], QB[1:]):
                    bloom_range.append([f,t])
                bloom_range.append([QB[-1], self._nroots])
                self._bloom_range = np.array(bloom_range) # N x 2 array of [from, to)
                self._bloom_files = _lsv(args.bloom_dir, args.prefix_bloom, '.npz')
                assert len(self._bloom_files) == self._nroots, "number of roots ({}) should match number of blooming files ({}). Maybe there is legacy files in bloom_dir?".format(self._nroots, len(self._bloom_files))

    def _solve_root_and_pds(self):
        G = self._G = nx.Graph()
        G.add_nodes_from([-1 - i for i in range(self._nroots)]) # Root nodes
        G.add_nodes_from(self._pds_ids)
        print("Loading edges from {}".format(self._args.forest_edge))
        tups = _load(self._args.forest_edge, 'E')[:].astype(np.int64)
        if False:
            print("OpenSet algorithm is disabled")
            self.openset = None
        else:
            print("Loading openset from {}".format(self._args.forest_edge))
            self.openset = _load(self._args.forest_edge, 'OpenTree')[:]
            if self.openset is not None:
                G.add_nodes_from([VIRTUAL_OPEN_SPACE_NODE])
                print('Open set shape {}'.format(self.openset.shape))
                # print('Open set data {}'.format(list(self.openset)))
        '''
        Correct the pds milestone ID from 1-indexed to 0-indexed
        We used 1-indexed ID because 0 was reserved as "no edge"
        '''
        tups[:, 2] -= 1
        # print('Open set shape {}'.format(self.openset.shape))
        # exit()
        edges_1 = tups[:,[0,2]]
        edges_2 = tups[:,[1,2]]
        # print(tups[:5])
        edges_1[:,0] = -1 - edges_1[:,0]
        edges_2[:,0] = -1 - edges_2[:,0]
        print(edges_1[:5])
        print(edges_2[:5])
        #return
        G.add_edges_from(edges_1)
        G.add_edges_from(edges_2)
        if self._bloom_range is not None:
            for root in range(self._nroots):
                f, t = self._bloom_range[root]
                edges_3 = np.zeros((t - f, 2), dtype=np.int64)
                edges_3[:,0] = -1 - root
                edges_3[:,1] = np.array([i for i in range(f, t)])
                G.add_edges_from(edges_3)
        # print(nx.shortest_path(G, -1, -1026))
        # -1: Root 0 (init), -2: Root 1 (goal)
        init_tree = -1
        goal_tree = -2
        if self.openset is not None:
            '''
            Add virtual edges
            1. trees in self.openset to a virtual open set node
            2. the virtual open set node to the vritual open set tree

            Also change goal_tree to the virtual open set tree
            '''
            virtual_edges = []
            for root in self.openset:
                # print("add edge ({} {})".format(-1 - root, VIRTUAL_OPEN_SPACE_NODE))
                virtual_edges.append((-1 - root, VIRTUAL_OPEN_SPACE_NODE))
            G.add_edges_from(virtual_edges)
            goal_tree = VIRTUAL_OPEN_SPACE_NODE
        try:
            self._sssp = nx.shortest_path(G, init_tree, goal_tree)
            print('Forest-level shortest path {}'.format(self._sssp))
        except nx.exception.NetworkXNoPath:
            return False
        return True

    def _solve_in_single_tree(self, n_from, n_to):
        if isinstance(n_from, complex):
            return None
        if n_from < 0:
            root,leaf = -(n_from + 1), n_to
            reverse = True
        else:
            root, leaf = -(n_to + 1), n_from
            reverse = False
        tree = self._cache_lookup(root)
        if tree is None:
            bloom_range = None if self._bloom_range is None else self._bloom_range[root]
            bloom_fn = None if self._bloom_files is None else self._bloom_files[root]
            tree = TreePathFinder(root=self._roots[root],
                                  ssc_fn=self._ssc_files[root],
                                  ct_fn=self._ct_files[root],
                                  pds=self._pds,
                                  pds_ids=self._pds_ids,
                                  pds_flags=self._pds_flags,
                                  bloom_range=bloom_range,
                                  bloom_fn=bloom_fn)
        path = tree.nodelist_from_root(leaf)
        self._cache_tree(tree, root)
        if reverse:
            return np.array(path[::-1])
        else:
            return np.array(path)

    def _cache_lookup(self, root):
        if root == self._cached_tree_root:
            return self._cached_tree
        return None

    def _cache_tree(self, tree, root):
        self._cached_tree = tree
        self._cached_tree_root = root

    def solve(self):
        if not self._solve_root_and_pds():
            return False
        # Sanity check!
        bugnode = []
        for root in self._sssp:
            if isinstance(root, complex) or root >= 0:
                continue
            index = -(root + 1)
            ct_fn = self._ct_files[index]
            d = loadmat(ct_fn)
            if np.min(d['CE']) != -1:
                bugnode.append(index)
        if bugnode:
            print("These nodes are buggy:\n{}".format(bugnode))
        # print('-1 to 4162147 {}'.format(self._solve_in_single_tree(-1, 4162147)))
        # return
        path = None
        # path = self._solve_in_single_tree(-1, 12342)
        pairs = [e for e in zip(self._sssp[:-1], self._sssp[1:])]
        print(pairs)
        for n_from,n_to in progressbar(pairs):
            traj = self._solve_in_single_tree(n_from, n_to)
            if traj is not None:
                path = traj if path is None else np.concatenate((path, traj), axis=0)
        self._sssp_full = path
        return True

    def output(self):
        print(self._pds_size)
        print(self._nroots)
        if self._args.out is None:
            print(self._sssp)
            print(self._sssp_full)
        else:
            np.savetxt(self._args.out, self._sssp_full, fmt='%.17g')

def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--indir', help='input directory for ssc-*.mat and file', required=True)
    parser.add_argument('--rootf', help='Roots of forest file', required=True)
    parser.add_argument('--pdsf', help='PreDefined sample Set File', required=True)
    parser.add_argument('--forest_edge', help='Pre-processed edge file from pds_edge.py', required=True)
    parser.add_argument('--prefix_ct', help='File name prefix of compact tree file ', default='compact_tree-')
    parser.add_argument('--prefix_ssc', help='File name prefix of sample set connectivity (ssc) file', default='ssc-')
    # Prerequisites to use Blooming trees in forest_dijkstra.
    # 1. QB array presents in --pdsf
    # 2. --bloom_dir is specified
    parser.add_argument('--bloom_dir', help='Directory of PDS blooming trees', default=None)
    parser.add_argument('--prefix_bloom', help='File name prefix of blooming files', default='bloom-from_')
    parser.add_argument('--out', help='Output path file. default to stdout', default=None)
    args = parser.parse_args()
    fpf = ForestPathFinder(args)
    if fpf.solve():
        fpf.output()

if __name__ == '__main__':
    main()
