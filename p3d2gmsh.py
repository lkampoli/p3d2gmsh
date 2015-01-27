#!/usr/bin/env python

"""Convert files from NASA 3D mesh format to Gmsh."""

from __future__ import print_function, division
import sys
import argparse
import os.path
import numpy as np
from ctypes import CDLL, c_int, byref, c_double

# File API.
#
# A FILE_ptr type is used instead of c_void_p because technically a pointer
# to structure can have a different size or alignment to a void pointer.
#
# Note that the file api may change.
#
try:
    import ctypes

    class FILE(ctypes.Structure):
        pass
    FILE_ptr = ctypes.POINTER(FILE)

    PyFile_FromFile = ctypes.pythonapi.PyFile_FromFile
    PyFile_FromFile.restype = ctypes.py_object
    PyFile_FromFile.argtypes = [FILE_ptr,
                                ctypes.c_char_p,
                                ctypes.c_char_p,
                                ctypes.CFUNCTYPE(ctypes.c_int, FILE_ptr)]

    PyFile_AsFile = ctypes.pythonapi.PyFile_AsFile
    PyFile_AsFile.restype = FILE_ptr
    PyFile_AsFile.argtypes = [ctypes.py_object]
except AttributeError:
    del FILE_ptr


class NeutralMapFile(object):
    def __init__(self, filename=None):
        self.__boundaries = []
        if filename is not None:
            fp = open(filename, 'r')
            # Skip initial comments
            for _ in xrange(4):
                fp.readline()
            # Blocks
            l = fp.readline()
            l = l[0:-2]
            nblocks = int(l)
            fp.readline()
            for _ in xrange(nblocks):
                fp.readline()
            fp.readline()
            # Middle comments
            for _ in range(3):
                fp.readline()
            # Boundaries
            for l in fp:
                if l.endswith('\\'):
                    b = l[0:-2].split()
                else:
                    b = l.split()
                if len(b) > 0:
                    b[0] = b[0][1:-1]
                    if b[0] == 'one-to-one':
                        continue
                    b[1:] = map(int, b[1:7])
                    self.__boundaries.append(tuple(b))
            fp.close()

    @property
    def boundaries(self):
        return self.__boundaries

    def __str__(self):
        return 'Neutral map file / {0:d} boundaries'.format(
            len(self.__boundaries))


class P3DfmtFile(object):

    """P3Dfmt file representation."""

    def __init__(self, filename=None, **kwargs):
        """Construct from components or load from file."""
        if filename:
            self.load(filename=filename)
        else:
            if kwargs is not None:
                self.__nblocks = kwargs['nblocks'] \
                    if 'nblocks' in kwargs else 0
                self.__coords = kwargs['coords'] \
                    if 'coords' in kwargs else None
            else:
                self.__nblocks = None
                self.__coords = None

    @property
    def nblocks(self):
        """Number of blocks in the file."""
        return self.__nblocks

    def idims(self, nblk=1):
        """Return i-dimensions of the file."""
        return self.__coords[nblk - 1][0].shape[0]

    def jdims(self, nblk=1):
        """Return j-dimensions of the file."""
        return self.__coords[nblk - 1][0].shape[1]

    def kdims(self, nblk=1):
        """Return j-dimensions of the file."""
        return self.__coords[nblk - 1][0].shape[2]

    @property
    def coords(self):
        """Return coordinates stored in the file."""
        return self.__coords

    def load(self, filename):
        """Load mesh blocks from the given file."""
        if sys.platform == 'darwin':
            libc = CDLL('libc.dylib')
        elif sys.platform == 'linux2':
            libc = CDLL('libc.so.6')
        else:
            raise OSError('Unsupported OS.')
        fscanf = libc.fscanf
        tmp = c_int()
        fp = open(filename)

        # Reading number of blocks
        fscanf(PyFile_AsFile(fp), '%d', byref(tmp))
        self.__nblocks = tmp.value

        # Reading dimensions
        idims = np.zeros(self.__nblocks, 'i')
        jdims = np.zeros(self.__nblocks, 'i')
        kdims = np.zeros(self.__nblocks, 'i')

        for i in xrange(self.__nblocks):
            fscanf(PyFile_AsFile(fp), '%d', byref(tmp))
            idims[i] = tmp.value
            fscanf(PyFile_AsFile(fp), '%d', byref(tmp))
            jdims[i] = tmp.value
            fscanf(PyFile_AsFile(fp), '%d', byref(tmp))
            kdims[i] = tmp.value

        # Reading coordinates
        ftmp = c_double()
        self.__coords = []

        for i in xrange(self.__nblocks):
            idim = idims[i]
            jdim = jdims[i]
            kdim = kdims[i]
            x = np.zeros((idim, jdim, kdim), 'f8')
            y = np.zeros((idim, jdim, kdim), 'f8')
            z = np.zeros((idim, jdim, kdim), 'f8')

            coords = [x, y, z]
            for c in coords:
                for k in xrange(kdim):
                    for j in xrange(jdim):
                        for i in xrange(idim):
                            fscanf(PyFile_AsFile(fp), '%lf', byref(ftmp))
                            c[i, j, k] = ftmp.value

            self.__coords.append((x, y, z))

        fp.close()

    def __str__(self):
        idims = [x.shape[0] for x, _, _ in self.__coords]
        jdims = [x.shape[1] for x, _, _ in self.__coords]
        kdims = [x.shape[2] for x, _, _ in self.__coords]
        return 'P3Dfmt file (blocks: %d/idims: (%s)/jdims: (%s)/kdims: (%s)' % \
            (self.__nblocks, ' '.join(map(str, idims)),
             ' '.join(map(str, jdims)), ' '.join(map(str, kdims)))

    def save(self, filename=None):
        """Save file, to stdout if no filename is given."""
        raise NotImplementedError

    def dump_coords(self):
        """Dump coordinates of the file as a list."""
        for n in xrange(self.__nblocks):
            idim = self.__coords[n][0].shape[0]
            jdim = self.__coords[n][0].shape[1]
            kdim = self.__coords[n][0].shape[2]

            x, y, z = self.__coords[n]

            for i in xrange(idim):
                for j in xrange(jdim):
                    for k in xrange(kdim):
                        print('%lf %lf %lf' % (x[i, j, k], y[i, j, k],
                                               z[i, j, k]))


class GmshFile(object):

    """Gmsh file representation."""

    # For conversion purposes I need only two types of elements:
    # - quadrangle (3) for the faces
    # - hexagon (5) for the cells
    # So there will be no constants.

    def __init__(self, nodes=None, elements=None, groups=None,
                 filename=None):
        """Construct from components.

        If filename is provided object is loaded from the file.

        :nodes:
            List of node tuples

        :elements:
            List of element tuples

        :groups:
            List of group tuples

        :filename:
            Name of file to load data from
        """
        self.__element_id = 0
        if filename:
            self.__nodes = []
            self.__elements = []
            self.__groups = []
            self.load(filename)
        else:
            self.__nodes = [] if nodes is None else nodes
            self.__elements = [] if elements is None else elements
            self.__groups = [] if groups is None else groups

    @property
    def nodes(self):
        """Return nodes of the current file."""
        return self.__nodes

    @property
    def elements(self):
        """Return elements of the current file."""
        return self.__elements

    @property
    def groups(self):
        """Return physical groups of the current file."""
        return self.__groups

    def load(self, filename=None):
        """Load nodes, elements, and groups from the given file."""
        raise NotImplementedError

    def __str__(self):
        """Create string representation of the file."""
        return 'GMSH file (nodes: %d, elements: %d, groups: %d)' % \
            (len(self.__nodes), len(self.__elements), len(self.__groups))

    def save(self, filename=None):
        """Save file, to stdout if no filename is given."""
        if filename:
            fp = open(filename, 'w')
        else:
            fp = sys.stdout

        self._write_header(fp)
        self._write_groups(fp)
        self._write_nodes(fp)
        self._write_elements(fp)

    def _write_header(self, out):
        out.write('$MeshFormat\n')
        out.write('2.2 0 8\n')
        out.write('$EndMeshFormat\n')

    def _write_groups(self, out):
        out.write('$PhysicalNames\n')
        out.write('%d\n' % len(self.__groups))
        for grp in self.__groups:
            out.write('%d %d "%s"\n' % grp)
        out.write('$EndPhysicalNames\n')

    def _write_nodes(self, out):
        out.write('$Nodes\n')
        out.write('%d\n' % len(self.__nodes))
        for node in self.__nodes:
            out.write('%d %15.13e %15.13e %15.13e\n' % node)
        out.write('$EndNodes\n')

    def _write_elements(self, out):
        out.write('$Elements\n')
        out.write('%d\n' % len(self.__elements))
        for el in self.__elements:
            out.write('%s\n' % ' '.join(map(str, el)))
        out.write('$EndElements\n')

    def consume(self, p3dfmt_file, mapfile=None):
        """Convert P3Dfmt file into self.

        :p3dfmt_file:
            P3DfmtFile object to convert.

        :mapfile:
            Neutral map file name, for boundary faces
        """
        self.__groups.append((3, 1, 'mesh'))
        for blkn in xrange(p3dfmt_file.nblocks):
            self._consume_block(p3dfmt_file, blkn)

        for bdry in mapfile.boundaries:
            self._gen_boundary(p3dfmt_file, bdry)

    @staticmethod
    def __find_smallest_cell(p2dfmt_file):
        for blk in xrange(p2dfmt_file.nblocks):
            x, y = p2dfmt_file.coords[blk]
            idim, jdim = x.shape
            dx = x[1, 0] - x[0, 0]
            dy = y[0, 1] - y[0, 0]
            for i in xrange(1, idim):
                for j in xrange(1, jdim):
                    dx = min(dx, x[i, j] - x[i - 1, j])
                    dy = min(dy, y[i, j] - y[i, j - 1])
        return min(dx, dy)

    @staticmethod
    def _p3d_node_id(p3dfmt_file, n, i, j, k):
        if n >= p3dfmt_file.nblocks:
            raise IndexError('Block number %d is out of range.' % n)

        basen = 1
        if p3dfmt_file.nblocks > 1:
            for idx in xrange(n):
                x, _, _ = p3dfmt_file.coords[idx]
                di, dj, dk = x.shape
                basen += di*dj*dk

        x, _, _ = p3dfmt_file.coords[n]
        _, dj, dk = x.shape

        return basen + k + dk*j + dk*dj*i

    def get_next_element_id(self):
        self.__element_id += 1
        return self.__element_id

    def _consume_block(self, p3dfmt_file, blkn):
        x, y, z = p3dfmt_file.coords[blkn]
        idim, jdim, kdim = x.shape

        # Filling nodes list
        for i in xrange(idim):
            for j in xrange(jdim):
                for k in xrange(kdim):
                    node_id = GmshFile._p3d_node_id(p3dfmt_file, blkn, i, j, k)
                    self.__nodes.append((node_id, x[i, j, k], y[i, j, k],
                                         z[i, j, k]))

        # Generating 3D elements
        shifts = [
            [0, -1, -1],
            [0,  0, -1],
            [0,  0,  0],
            [0, -1,  0],
            [1, -1, -1],
            [1,  0, -1],
            [1,  0,  0],
            [1, -1,  0],
        ]

        for j in xrange(1, jdim):
            for k in xrange(1, kdim):
                el_id = self.get_next_element_id()
                el = [el_id, 5, 2, 1, -1]
                for s in shifts:
                    el.append(GmshFile._p3d_node_id(p3dfmt_file, blkn, s[0],
                                                    j + s[1], k + s[2]))
                self.__elements.append(el)

    def _next_group_id(self):
        return max(self.__groups, key=lambda n: n[1])[1] + 1

    def _gen_boundary(self, p3df, bdry):
        gid = self._next_group_id()
        nb = (2, gid, 'b{0:d}-{1}'.format(gid, bdry[0]))
        self.__groups.append(nb)

        blkn = bdry[1] - 1
        blk = p3df.coords[blkn]
        x, _, _ = blk

        imax = x.shape[0] - 1
        jmax = x.shape[1] - 1
        kmax = x.shape[2] - 1

        s1, e1, s2, e2 = bdry[3:7]
        if bdry[2] == 1:
            for j in xrange(s2 - 1, e2 - 1):
                for i in xrange(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, i, j, 0)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, i + 1, j, 0)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, i + 1, j + 1, 0)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, i, j + 1, 0)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        elif bdry[2] == 2:
            for j in xrange(s2 - 1, e2 - 1):
                for i in xrange(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, i, j, kmax)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, i + 1, j, kmax)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, i + 1, j + 1, kmax)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, i, j + 1, kmax)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        elif bdry[2] == 3:
            for k in xrange(s2 - 1, e2 - 1):
                for j in xrange(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, 0, j, k)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, 0, j + 1, k)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, 0, j + 1, k + 1)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, 0, j, k + 1)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        elif bdry[2] == 4:
            for k in xrange(s2 - 1, e2 - 1):
                for j in xrange(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, imax, j, k)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, imax, j + 1, k)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, imax, j + 1, k + 1)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, imax, j, k + 1)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        elif bdry[2] == 5:
            for i in xrange(s2 - 1, e2 - 1):
                for k in range(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, i, 0, k)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, i + 1, 0, k)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, i + 1, 0, k + 1)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, i, 0, k + 1)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        elif bdry[2] == 6:
            for i in xrange(s2 - 1, e2 - 1):
                for k in xrange(s1 - 1, e1 - 1):
                    el_id = self.get_next_element_id()
                    n1 = GmshFile._p3d_node_id(p3df, blkn, i, jmax, k)
                    n2 = GmshFile._p3d_node_id(p3df, blkn, i + 1, jmax, k)
                    n3 = GmshFile._p3d_node_id(p3df, blkn, i + 1, jmax, k + 1)
                    n4 = GmshFile._p3d_node_id(p3df, blkn, i, jmax, k + 1)

                    self.__elements.append([el_id, 3, 2, gid, -1, n1, n2, n3,
                                            n4])

        else:
            raise ValueError('Unknown block face identifier.')


def main():
    """Parse command line options, convert files."""
    # CLI options:
    # --output-file / -o: write resulting mesh into
    # --map-file / -m: read boundary description from

    parser = argparse.ArgumentParser(description='''\
        Convert P3Dfmt mesh into Gmsh mesh''', add_help=True)
    parser.add_argument('files', nargs='+', help='files to convert')
    parser.add_argument('-m', '--map-file', nargs=1, help='''\
        Neutral Map File, if omitted script will look for <filename>.nmf
                        file''')
    parser.add_argument('-o', '--output-file', nargs=1, help='''\
        output file name, if omitted mesh will be written to <filename>.msh''')
    args = parser.parse_args()

    for fn in args.files:
        if not os.path.exists(fn):
            print('Can\'t open {0}. Skipping.'.format(fn))
            continue
        (name, ext) = os.path.splitext(fn)

        mapfile = None
        outputfile = None
        if args.map_file is None:
            mapfile = '{0}.nmf'.format(name)
        else:
            mapfile = args.map_file

        if args.output_file is None:
            outputfile = '{0}.msh'.format(name)
        else:
            outputfile = args.output_file

        p3d = P3DfmtFile()
        p3d.load(fn)
        nmf = NeutralMapFile(mapfile)

        gmsh = GmshFile()
        gmsh.consume(p3d, mapfile=nmf)
        gmsh.save(outputfile)


if __name__ == '__main__':
    main()
