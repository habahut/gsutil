# Copyright 2010 Google Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

"""Tests for gsutil commands.
The test code in this file runs against an in-memory storage service mock,
so runs very quickly. This is valuable for testing changes that impact the
naming rules, since those rules are complex and it's useful to be able to
make small incremental changes and rerun the tests frequently. Additional
end-to-end tests (which send traffic to the production Google Cloud Storage
service) are available via the gsutil test command.
"""

import os
import shutil
import tempfile
import time

import boto
from boto.exception import StorageResponseError
from boto import storage_uri

from gslib import wildcard_iterator
from gslib.commands import cp
from gslib.exception import CommandException
import gslib.tests.testcase as testcase


class GsutilCommandTests(testcase.GsUtilUnitTestCase):
  """gsutil command method test suite"""

  def tearDown(self):
    """Deletes any objects or files created by last test run"""
    super(GsutilCommandTests, self).tearDown()
    try:
      for key_uri in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_uri).IterUris():
        key_uri.delete_key()
    # For some reason trying to catch except
    # wildcard_iterator.WildcardException doesn't work here.
    except Exception:
      # Ignore cleanup failures.
      pass
    # Recursively delete dst dir and then re-create it, so in effect we
    # remove all dirs and files under that directory.
    shutil.rmtree(self.dst_dir_root)
    os.mkdir(self.dst_dir_root)

  @classmethod
  def SrcFile(cls, fname):
    """Returns path for given test src file"""
    for path in cls.all_src_file_paths:
      if path.find(fname) != -1:
        return path
    raise Exception('SrcFile(%s): no match' % fname)

  @classmethod
  def CreateEmptyObject(cls, uri):
    """Creates an empty object for the given StorageUri"""
    key = uri.new_key()
    key.set_contents_from_string('')

  @classmethod
  def setUpClass(cls):
    """Initializes test suite.

    Creates a source bucket containing 9 objects, 3 of which live under a
    subdir, 3 of which lives under a nested subdir; a source directory
    containing a subdirectory and file; and a destination bucket and directory.
    """
    testcase.GsUtilUnitTestCase.setUpClass()
    cls.uri_base_str = 'gs://gsutil_test_%s' % int(time.time())
    # Use a designated tmpdir prefix to make it easy to find the end of
    # the tmp path.
    cls.tmpdir_prefix = 'tmp_gstest'

    # Create the test buckets.
    cls.src_bucket_uri = cls._test_storage_uri('%s_src' % cls.uri_base_str)
    cls.dst_bucket_uri = cls._test_storage_uri('%s_dst' % cls.uri_base_str)
    cls.src_bucket_uri.create_bucket()

    # Define the src and dest bucket subdir paths. Note that they exclude
    # a slash on the end so we can test handling of bucket subdirs specified
    # both with and without terminating slashes.
    cls.src_bucket_subdir_uri = cls._test_storage_uri(
        '%s_src/src_subdir' % cls.uri_base_str)
    cls.src_bucket_subdir_uri_wildcard = cls._test_storage_uri(
        '%s_src/src_sub*' % cls.uri_base_str)
    cls.dst_bucket_subdir_uri = cls._test_storage_uri(
        '%s_dst/dst_subdir' % cls.uri_base_str)
    cls.dst_bucket_uri.create_bucket()

    # Create the test objects in the src bucket.
    cls.all_src_obj_uris = []
    cls.all_src_top_level_obj_uris = []
    cls.all_src_subdir_obj_uris = []
    cls.all_src_subdir_and_below_obj_uris = []
    for i in range(3):
      obj_uri = cls._test_storage_uri('%sobj%d' % (cls.src_bucket_uri, i))
      cls.CreateEmptyObject(obj_uri)
      cls.all_src_obj_uris.append(obj_uri)
      cls.all_src_top_level_obj_uris.append(obj_uri)
    # Subdir objects
    for i in range(4, 6):
      obj_uri = cls._test_storage_uri(
          '%s/obj%d' % (cls.src_bucket_subdir_uri, i))
      cls.CreateEmptyObject(obj_uri)
      cls.all_src_obj_uris.append(obj_uri)
      cls.all_src_subdir_obj_uris.append(obj_uri)
      cls.all_src_subdir_and_below_obj_uris.append(obj_uri)
    # Nested subdir objects
    for i in range(7, 9):
      obj_uri = cls._test_storage_uri(
          '%s/nested/obj%d' % (cls.src_bucket_subdir_uri, i))
      cls.CreateEmptyObject(obj_uri)
      cls.all_src_obj_uris.append(obj_uri)
      cls.all_src_subdir_and_below_obj_uris.append(obj_uri)

    # Create the test directories.
    cls.src_dir_root = '%s%s' % (tempfile.mkdtemp(prefix=cls.tmpdir_prefix),
                                 os.sep)
    nested_subdir = '%sdir0%sdir1' % (cls.src_dir_root, os.sep)
    os.makedirs(nested_subdir)
    cls.dst_dir_root = '%s%s' % (tempfile.mkdtemp(prefix=cls.tmpdir_prefix),
                                 os.sep)

    # Create the test files in the src directory.
    cls.all_src_file_paths = []
    cls.nested_child_file_paths = ['f0', 'f1', 'f2.txt', 'dir0/dir1/nested']
    cls.non_nested_file_names = ['f0', 'f1', 'f2.txt']
    file_names = ['f0', 'f1', 'f2.txt', 'dir0%sdir1%snested' % (os.sep, os.sep)]
    file_paths = ['%s%s' % (cls.src_dir_root, f) for f in file_names]
    for file_path in file_paths:
      f = open(file_path, 'w')
      f.write('test data')
      f.close()
      cls.all_src_file_paths.append(file_path)
    cls.tmp_path = '%s%s' % (cls.src_dir_root, 'tmp0')

    cls.created_test_data = True

  @classmethod
  def tearDownClass(cls):
    """Cleans up buckets and directories created by setUpClass"""
    testcase.GsUtilUnitTestCase.tearDownClass()
    if not hasattr(cls, 'created_test_data'):
      return
    # Now delete src objects and files, and all buckets and dirs.
    try:
      for key_uri in cls._test_wildcard_iterator(
          '%s**' % cls.src_bucket_uri).IterUris():
        key_uri.delete_key()
    except wildcard_iterator.WildcardException:
      # Ignore cleanup failures.
      pass
    try:
      for key_uri in cls._test_wildcard_iterator(
          '%s**' % cls.src_dir_root).IterUris():
        key_uri.delete_key()
    except wildcard_iterator.WildcardException:
      # Ignore cleanup failures.
      pass
    cls.src_bucket_uri.delete_bucket()
    cls.dst_bucket_uri.delete_bucket()
    shutil.rmtree(cls.src_dir_root)
    shutil.rmtree(cls.dst_dir_root)

  def testGetPathBeforeFinalDir(self):
    """Tests _GetPathBeforeFinalDir() (unit test)"""
    self.assertEqual('gs://',
                     cp._GetPathBeforeFinalDir(storage_uri('gs://bucket/')))
    self.assertEqual('gs://bucket',
                     cp._GetPathBeforeFinalDir(storage_uri('gs://bucket/dir/')))
    self.assertEqual('gs://bucket',
                     cp._GetPathBeforeFinalDir(storage_uri('gs://bucket/dir')))
    self.assertEqual('gs://bucket/dir',
                     cp._GetPathBeforeFinalDir(
                         storage_uri('gs://bucket/dir/obj')))
    self.assertEqual('file://%s' % self.src_dir_root.rstrip('/'),
                     cp._GetPathBeforeFinalDir(storage_uri(
                         'file://%sdir0/' % self.src_dir_root)))

  def testCopyingTopLevelFileToBucket(self):
    """Tests copying one top-level file to a bucket"""
    src_file = self.SrcFile('f0')
    self.RunCommand('cp', [src_file, self.dst_bucket_uri.uri])
    actual = list(self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def testCopyingAbsolutePathDirToBucket(self):
    """Tests recursively copying absolute path directory to a bucket"""
    self.RunCommand('cp', ['-R', self.src_dir_root, self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%s%s' % (self.dst_bucket_uri.uri,
                             file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def testCopyingRelativePathDirToBucket(self):
    """Tests recursively copying relative directory to a bucket"""
    orig_dir = os.getcwd()
    os.chdir(self.src_dir_root)
    self.RunCommand('cp', ['-R', 'dir0', self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%s%s' % (self.dst_bucket_uri.uri, 'dir0/dir1/nested'))
    self.assertEqual(expected, actual)
    os.chdir(orig_dir)

  def testCopyingRelativePathSubDirToBucketSubdirSignifiedByDollarFolderObj(self):
    """Tests recursively copying relative sub-directory to bucket subdir signified by a $folder$ object"""
    orig_dir = os.getcwd()
    os.chdir(self.src_dir_root)
    # Create a $folder$ object to simulate a folder created by GCS manager (or
    # various other tools), which gsutil understands to mean there is a folder into
    # which the object is being copied.
    obj_name = '%sabc_$folder$' % self.dst_bucket_uri
    self.CreateEmptyObject(self._test_storage_uri(obj_name))
    self.RunCommand('cp', ['-R', 'dir0/dir1', '%sabc'
                    % self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set([obj_name])
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%sabc/%s' % (self.dst_bucket_uri.uri, 'dir1/nested'))
    self.assertEqual(expected, actual)
    os.chdir(orig_dir)

  def testCopyingRelativePathSubDirToBucketSubdirSignifiedBySlash(self):
    """Tests recursively copying relative sub-directory to bucket subdir signified by a / object"""
    orig_dir = os.getcwd()
    os.chdir(self.src_dir_root)
    self.RunCommand('cp', ['-R', 'dir0/dir1', '%sabc/'
                    % self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%sabc/%s' % (self.dst_bucket_uri.uri, 'dir1/nested'))
    self.assertEqual(expected, actual)
    os.chdir(orig_dir)

  def testCopyingRelativePathSubDirToBucket(self):
    """Tests recursively copying relative sub-directory to a bucket"""
    orig_dir = os.getcwd()
    os.chdir(self.src_dir_root)
    self.RunCommand('cp', ['-R', 'dir0/dir1', self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('%s%s' % (self.dst_bucket_uri.uri, 'dir1/nested'))
    self.assertEqual(expected, actual)
    os.chdir(orig_dir)

  def testCopyingDotSlashToBucket(self):
    """Tests copying ./ to a bucket produces expected naming"""
    # When running a command like gsutil cp -r . gs://dest we expect the dest
    # obj names to be of the form gs://dest/abc, not gs://dest/./abc.
    orig_dir = os.getcwd()
    for rel_src_dir in ['.', './']:
      os.chdir(self.src_dir_root)
      self.RunCommand('cp', ['-R', rel_src_dir, self.dst_bucket_uri.uri])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_uri.uri).IterUris())
      expected = set()
      for file_path in self.all_src_file_paths:
        start_tmp_pos = (file_path.find(self.src_dir_root)
                         + len(self.src_dir_root))
        file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
        expected.add('%s%s' % (self.dst_bucket_uri.uri,
                               file_path_sans_top_tmp_dir))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()
      os.chdir(orig_dir)

  def testCopyingDirContainingOneFileToBucket(self):
    """Tests copying a directory containing 1 file to a bucket.
    We test this case to ensure that correct bucket handling isn't dependent
    on the copy being treated as a multi-source copy.
    """
    self.RunCommand('cp', ['-R', '%sdir0%sdir1' %
                    (self.src_dir_root, os.sep),
                    self.dst_bucket_uri.uri])
    actual = list((str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris()))
    self.assertEqual(1, len(actual))
    self.assertEqual('%sdir1%snested' % (self.dst_bucket_uri.uri, os.sep),
                     actual[0])

  def testCopyingBucketToDir(self):
    """Tests copying from a bucket to a directory"""
    self.RunCommand('cp', ['-R', self.src_bucket_uri.uri, self.dst_dir_root])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_dir_root).IterUris())
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('file://%s%s/%s' % (self.dst_dir_root, uri.bucket_name,
                                       uri.object_name))
    self.assertEqual(expected, actual)

  def testCopyingBucketToBucket(self):
    """Tests copying from a bucket-only URI to a bucket"""
    self.RunCommand('cp', ['-R', self.src_bucket_uri.uri,
                    self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%s%s/%s' % (self.dst_bucket_uri.uri, uri.bucket_name,
                                uri.object_name))
    self.assertEqual(expected, actual)

    """Tests copying from a directory to a directory"""
    self.RunCommand('cp', ['-R', self.src_dir_root, self.dst_dir_root])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_dir_root).IterUris())
    expected = set()
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_top_tmp_dir = file_path[start_tmp_pos:]
      expected.add('file://%s%s' % (self.dst_dir_root,
                                    file_path_sans_top_tmp_dir))
    self.assertEqual(expected, actual)

  def testCopyingFilesAndDirNonRecursive(self):
    """Tests copying containing files and a directory without -R"""
    self.RunCommand('cp', ['%s*' % self.src_dir_root, self.dst_dir_root])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_dir_root).IterUris())
    expected = set(['file://%s%s' % (self.dst_dir_root, f)
                    for f in self.non_nested_file_names])
    self.assertEqual(expected, actual)

  def testCopyingFileToDir(self):
    """Tests copying one file to a directory"""
    src_file = self.SrcFile('nested')
    self.RunCommand('cp', [src_file, self.dst_dir_root])
    actual = list(self._test_wildcard_iterator(
        '%s*' % self.dst_dir_root).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('file://%s%s' % (self.dst_dir_root, 'nested'),
                     actual[0].uri)

  def testCopyingFileToObjectWithConsecutiveSlashes(self):
    """Tests copying a file to an object containing consecutive slashes"""
    src_file = self.SrcFile('f0')
    self.RunCommand('cp', [src_file, '%s/obj' % self.dst_bucket_uri.uri])
    actual = list(self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('/obj', actual[0].object_name)

  def testCopyingCompressedFileToBucket(self):
    """Tests copying one file with compression to a bucket"""
    src_file = self.SrcFile('f2.txt')
    self.RunCommand('cp', ['-z', 'txt', src_file, self.dst_bucket_uri.uri],)
    actual = list(
        str(u) for u in self._test_wildcard_iterator(
            '%s*' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    expected_dst_uri = self.dst_bucket_uri.clone_replace_name('f2.txt')
    self.assertEqual(expected_dst_uri.uri, actual[0])
    dst_key = expected_dst_uri.get_key()
    dst_key.open_read()
    self.assertEqual('gzip', dst_key.content_encoding)

  def testCopyingObjectToObject(self):
    """Tests copying an object to an object"""
    self.RunCommand('cp', ['%sobj1' % self.src_bucket_uri.uri,
                           self.dst_bucket_uri.uri])
    actual = list(self._test_wildcard_iterator(
        '%s*' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('obj1', actual[0].object_name)

  def testCopyingObjsAndFilesToDir(self):
    """Tests copying objects and files to a directory"""
    self.RunCommand('cp', ['-R', '%s**' % self.src_bucket_uri.uri,
                           '%s**' % self.src_dir_root, self.dst_dir_root])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_dir_root).IterUris())
    expected = set()
    for uri in self.all_src_obj_uris:
      # Use FinalObjNameComponent here because we expect names to be flattened
      # when using wildcard copy semantics.
      expected.add('file://%s%s' % (self.dst_dir_root,
                                    self.FinalObjNameComponent(uri)))
    for file_path in self.nested_child_file_paths:
      # Use os.path.basename here because we expect names to be flattened when
      # using wildcard copy semantics.
      expected.add('file://%s%s' % (self.dst_dir_root,
                                    os.path.basename(file_path)))
    self.assertEqual(expected, actual)

  def testCopyingObjToDot(self):
    """Tests that copying an object to . or ./ downloads to correct name"""
    for final_char in ('/', ''):
      prev_dir = os.getcwd()
      os.chdir(self.dst_dir_root)
      self.RunCommand('cp',
                      ['%sobj1' % self.src_bucket_uri.uri, '.%s' % final_char])
      actual = set()
      for dirname, dirnames, filenames in os.walk('.'):
        for subdirname in dirnames:
          actual.add(os.path.join(dirname, subdirname))
        for filename in filenames:
          actual.add(os.path.join(dirname, filename))
      expected = set(['./obj1'])
      self.assertEqual(expected, actual)
      os.chdir(prev_dir)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingObjsAndFilesToBucket(self):
    """Tests copying objects and files to a bucket"""
    self.RunCommand('cp', ['-R', '%s**' % self.src_bucket_uri.uri,
                           '%s**' % self.src_dir_root, self.dst_bucket_uri.uri])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s*' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for uri in self.all_src_obj_uris:
      # Use FinalObjNameComponent here because we expect names to be flattened
      # when using wildcard copy semantics.
      expected.add('%s%s' % (self.dst_bucket_uri.uri,
                             self.FinalObjNameComponent(uri)))
    for file_path in self.nested_child_file_paths:
      # Use os.path.basename here because we expect names to be flattened when
      # using wildcard copy semantics.
      expected.add('%s%s' % (self.dst_bucket_uri.uri,
                             os.path.basename(file_path)))
    self.assertEqual(expected, actual)

  def testAttemptDirCopyWithoutRecursion(self):
    """Tests copying a directory without -R"""
    try:
      self.RunCommand('cp', [self.src_dir_root,
                                            self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('No URIs matched'), -1)

  def testAttemptCopyingProviderOnlySrc(self):
    """Attempts to copy a src specified as a provider-only URI"""
    try:
      self.RunCommand('cp', ['gs://', self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('provider-only'), -1)

  def testAttemptCopyingOverlappingSrcDstFile(self):
    """Attempts to an object atop itself"""
    obj_uri = self._test_storage_uri('%sobj' % self.dst_bucket_uri)
    self.CreateEmptyObject(obj_uri)
    try:
      self.RunCommand('cp', ['%s/f0' % self.src_dir_root,
                             '%s/f0' % self.src_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('are the same file - abort'), -1)

  def testAttemptCopyingToMultiMatchWildcard(self):
    """Attempts to copy where dst wildcard matches >1 obj"""
    try:
      self.RunCommand('cp', ['%sobj0' % self.src_bucket_uri.uri,
                             '%s*' % self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('must match exactly 1 URI'), -1)

  def testAttemptCopyingMultiObjsToFile(self):
    """Attempts to copy multiple objects to a file"""
    # Use src_dir_root so we can point to an existing file for this test.
    try:
      self.RunCommand('cp', ['-R', '%s*' % self.src_bucket_uri.uri,
                             '%sf0' % self.src_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('must name a cloud path or '), -2)

  def testAttemptCopyingWithFileDirConflict(self):
    """Attempts to copy objects that cause a file/directory conflict"""
    # Create objects with name conflicts (a/b and a). Use 'dst' bucket because
    # it gets cleared after each test.
    self.CreateEmptyObject(self._test_storage_uri(
        '%sa/b' % self.dst_bucket_uri))
    self.CreateEmptyObject(self._test_storage_uri(
        '%sa' % self.dst_bucket_uri))
    try:
      self.RunCommand('cp', ['-R', self.dst_bucket_uri.uri,
                             self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find(
          'exists where a directory needs to be created'), -1)

  def testAttemptCopyingWithDirFileConflict(self):
    """Attempts to copy an object that causes a directory/file conflict"""
    # Create abc in dest dir.
    os.mkdir('%sabc' % self.dst_dir_root)
    # Create an object that conflicts with this dest subdir. Use 'dst' bucket
    # as source because it gets cleared after each test.
    obj_name = '%sabc' % self.dst_bucket_uri
    self.CreateEmptyObject(self._test_storage_uri(obj_name))
    try:
      self.RunCommand('cp', [obj_name, self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find(
          'where the file needs to be created'), -1)

  def testWildcardMoveWithinBucket(self):
    """Attempts to move using src wildcard that overlaps dest object.
    We want to ensure that this doesn't stomp the result data. See the
    comment starting with 'Expand wildcards before' in commands/mv.py
    for details.
    """
    # Create a single object; use 'dst' bucket because it gets cleared after
    # each test.
    self.CreateEmptyObject(
        self._test_storage_uri('%sold' % self.dst_bucket_uri))
    self.RunCommand('mv', ['%s*' % self.dst_bucket_uri.uri,
                           '%snew' % self.dst_bucket_uri.uri])
    actual = list(
        self._test_wildcard_iterator(
            '%s*' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('new', actual[0].object_name)

  def testCatCommandRuns(self):
    """Test that the cat command basically runs"""
    self.RunCommand('cat', ['%sobj1' % self.src_bucket_uri.uri])

  def testGetAclCommandRuns(self):
    """Test that the getacl command basically runs"""
    self.RunCommand('getacl', [self.src_bucket_uri.uri])

  def testGetDefAclCommandRuns(self):
    """Test that the getdefacl command basically runs"""
    self.RunCommand('getacl', [self.src_bucket_uri.uri])

  def testGetLoggingCommandRuns(self):
    """Test that the getlogging command basically runs"""
    self.RunCommand('getlogging', [self.src_bucket_uri.uri])

  def testHelpCommandDoesntRaise(self):
    """Test that the help command doesn't raise (sanity checks all help)"""
    # Unset PAGER if defined, so help output paginating into $PAGER doesn't
    # cause test to pause.
    if 'PAGER' in os.environ:
      del os.environ['PAGER']
    self.RunCommand('help', [])

  def testLsNonExistentObjectWithPrefixName(self):
    """Test ls of non-existent obj that matches prefix of existing objs"""
    # Use an object name that matches a prefix of other names at that level, to
    # ensure the ls subdir handling logic doesn't pick up anything extra.
    try:
      output = self.RunCommand('ls', ['%sobj' % self.src_bucket_uri.uri],
                               return_stdout=True)
    except CommandException, e:
      self.assertNotEqual(e.reason.find('No such object'), -1)

  def testLsBucketNonRecursive(self):
    """Test that ls of a bucket returns expected results"""
    output = self.RunCommand('ls', ['%s*' % self.src_bucket_uri.uri],
                             return_stdout=True)
    expected = set(x.uri for x in self.all_src_top_level_obj_uris)
    expected = expected.union(x.uri for x in self.all_src_subdir_obj_uris)
    expected.add('%ssrc_subdir/:' % self.src_bucket_uri.uri)
    expected.add('%ssrc_subdir/nested/' % self.src_bucket_uri.uri)
    expected.add('') # Blank line between subdir listings.
    actual = set(output.split('\n'))
    self.assertEqual(expected, actual)

  def testLsBucketRecursive(self):
    """Test that ls -R of a bucket returns expected results"""
    output = self.RunCommand('ls', ['-R', '%s*' % self.src_bucket_uri.uri],
                             return_stdout=True)
    expected = set(x.uri for x in self.all_src_obj_uris)
    expected = expected.union(x.uri for x in self.all_src_subdir_obj_uris)
    expected.add('%ssrc_subdir/:' % self.src_bucket_uri.uri)
    expected.add('%ssrc_subdir/nested/:' % self.src_bucket_uri.uri)
    expected.add('') # Blank line between subdir listings.
    actual = set(output.split('\n'))
    self.assertEqual(expected, actual)

  def testLsBucketRecursiveWithLeadingSlashObjectName(self):
    """Test that ls -R of a bucket with an object that has leading slash"""
    src_file = self.SrcFile('f0')
    self.RunCommand('cp', [src_file, '%s/%s' % (self.dst_bucket_uri.uri, 'f0')])
    output = self.RunCommand('ls', ['-R', '%s*' % self.dst_bucket_uri.uri],
                             return_stdout=True)
    expected = set(['%s/%s' % (self.dst_bucket_uri.uri, 'f0')])
    expected.add('') # Blank line between subdir listings.
    actual = set(output.split('\n'))
    self.assertEqual(expected, actual)

  def testLsBucketSubdirNonRecursive(self):
    """Test that ls of a bucket subdir returns expected results"""
    output = self.RunCommand('ls', ['%ssrc_subdir' % self.src_bucket_uri.uri],
                             return_stdout=True)
    expected = set(x.uri for x in self.all_src_subdir_obj_uris)
    expected = expected.union(x.uri for x in self.all_src_subdir_obj_uris)
    expected.add('%ssrc_subdir/nested/' % self.src_bucket_uri.uri)
    expected.add('') # Blank line between subdir listings.
    actual = set(output.split('\n'))
    self.assertEqual(expected, actual)

  def testLsBucketSubdirRecursive(self):
    """Test that ls -R of a bucket subdir returns expected results"""
    for final_char in ('/', ''):
      output = self.RunCommand('ls',
                               ['-R', '%ssrc_subdir%s'
                                % (self.src_bucket_uri.uri, final_char)],
                               return_stdout=True)
      expected = set(x.uri for x in self.all_src_subdir_and_below_obj_uris)
      expected = expected.union(x.uri for x in self.all_src_subdir_obj_uris)
      expected.add('%ssrc_subdir/:' % self.src_bucket_uri.uri)
      expected.add('%ssrc_subdir/nested/:' % self.src_bucket_uri.uri)
      expected.add('') # Blank line between subdir listings.
      actual = set(output.split('\n'))
      self.assertEqual(expected, actual)

  def testMakeBucketsCommand(self):
    """Test mb on existing bucket"""
    try:
      self.RunCommand('mb', [self.dst_bucket_uri.uri])
      self.fail('Did not get expected StorageCreateError')
    except boto.exception.StorageCreateError, e:
      self.assertEqual(e.status, 409)

  def testRemoveBucketsCommand(self):
    """Test rb on non-existent bucket"""
    try:
      self.RunCommand('rb', ['gs://non_existent_%s' %
                      self.dst_bucket_uri.bucket_name])
      self.fail('Did not get expected StorageResponseError')
    except boto.exception.StorageResponseError, e:
      self.assertEqual(e.status, 404)

  def testRemoveObjsCommand(self):
    """Test rm command on non-existent object"""
    try:
      self.RunCommand('rm', ['%snon_existent' %
                             self.dst_bucket_uri.uri])
      self.fail('Did not get expected WildcardException')
    except StorageResponseError, e:
      self.assertNotEqual(e.reason.find('Not Found'), -1)

  def testSetAclOnBucketRuns(self):
    """Test that the setacl command basically runs"""
    # We don't test reading back the acl (via getacl command) because at present
    # MockStorageService doesn't translate canned ACLs into actual ACL XML.
    self.RunCommand('setacl', ['private', self.src_bucket_uri.uri])

  def testSetAclOnWildcardNamedBucketRuns(self):
    """Test that setacl basically runs against wildcard-named bucket"""
    # We don't test reading back the acl (via getacl command) because at present
    # MockStorageService doesn't translate canned ACLs into actual ACL XML.
    uri_str = '%s_s*c' % self.uri_base_str
    self.RunCommand('setacl', ['private', uri_str])

  def testSetAclOnObjectRuns(self):
    """Test that the setacl command basically runs"""
    self.RunCommand('setacl', ['private', '%s*' % self.src_bucket_uri.uri])

  def testSetDefAclOnBucketRuns(self):
    """Test that the setdefacl command basically runs"""
    self.RunCommand('setdefacl', ['private', self.src_bucket_uri.uri])

  def testSetDefAclOnObjectFails(self):
    """Test that the setdefacl command fails when run against an object"""
    try:
      self.RunCommand('setdefacl', ['private', '%s*' % self.src_bucket_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('URI must name a bucket'), -1)

  def testDisableLoggingCommandRuns(self):
    """Test that the disablelogging command basically runs"""
    self.RunCommand('disablelogging', [self.src_bucket_uri.uri])

  def testEnableLoggingCommandRuns(self):
    """Test that the enablelogging command basically runs"""
    self.RunCommand('enablelogging', ['-b', 'gs://log_bucket',
                                      self.src_bucket_uri.uri])

  # Now that gsutil ver computes a checksum it adds 1-3 seconds to test run
  # time (for in memory mocked tests that otherwise take ~ 0.1 seconds). Since
  # it provides very little test value, we're leaving this test commented out.
  #def testVerCommmandRuns(self):
  #  """Test that the Ver command basically runs"""
  #  self.RunCommand('ver', [])

  def testMinusDOptionWorks(self):
    """Tests using gsutil -D option"""
    src_file = self.SrcFile('f0')
    self.RunCommand('cp', [src_file, self.dst_bucket_uri.uri], debug=3)
    actual = list(self._test_wildcard_iterator(
        '%s*' % self.dst_bucket_uri.uri).IterUris())
    self.assertEqual(1, len(actual))
    self.assertEqual('f0', actual[0].object_name)

  def DownloadTestHelper(self, func):
    """
    Test resumable download with custom test function to distort downloaded
    data. We expect an exception to be raised and the dest file to be removed.
    """
    object_uri = self.all_src_obj_uris[0].uri
    try:
      self.RunCommand('cp', [object_uri, self.tmp_path], test_method=func)
      self.fail('Did not get expected CommandException')
    except CommandException:
      self.assertFalse(os.path.exists(self.tmp_path))
    except:
      self.fail('Unexpected exception raised')

  def testDownloadWithObjectSizeChange(self):
    """
    Test resumable download on an object that changes size before the
    downloaded file's checksum is validated.
    """
    def append(fp):
      """Append a byte at end of an open file and flush contents."""
      fp.seek(0,2)
      fp.write('x')
      fp.flush()
    self.DownloadTestHelper(append)

  def testDownloadWithFileContentChange(self):
    """
    Tests resumable download on an object where the file content changes
    before the downloaded file's checksum is validated.
    """
    def overwrite(fp):
      """Overwrite first byte in an open file and flush contents."""
      fp.seek(0)
      fp.write('x')
      fp.flush()
    self.DownloadTestHelper(overwrite)

  def testFlatCopyingObjsAndFilesToBucketSubDir(self):
    """Tests copying flatly listed objects and files to bucket subdir"""
    # Test with and without final slash on dest subdir.
    for final_char in ('/', ''):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['-R', '%s**' % self.src_bucket_uri.uri,
                 '%s**' % self.src_dir_root,
                 '%sdst_subdir%s' % (self.dst_bucket_uri.uri, final_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_uri.uri).IterUris())
      expected = set(['%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      for uri in self.all_src_obj_uris:
        # Use FinalObjNameComponent here because we expect names to be flattened
        # when using wildcard copy semantics.
        expected.add('%sdst_subdir/%s' % (self.dst_bucket_uri.uri,
                                         self.FinalObjNameComponent(uri)))
      for file_path in self.nested_child_file_paths:
        # Use os.path.basename here because we expect names to be flattened when
        # using wildcard copy semantics.
        expected.add('%sdst_subdir/%s' % (self.dst_bucket_uri.uri,
                                         os.path.basename(file_path)))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testRecursiveCopyObjsAndFilesToExistingBucketSubDir(self):
    """Tests recursive copy of objects and files to existing bucket subdir"""
    # Test with and without final slash on dest subdir.
    for final_char in ('/', ''):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['-R', '%s' % self.src_bucket_uri.uri,
                 '%s' % self.src_dir_root,
                 '%sdst_subdir%s' % (self.dst_bucket_uri.uri, final_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_uri.uri).IterUris())
      expected = set(['%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      for uri in self.all_src_obj_uris:
        expected.add('%sdst_subdir/%s/%s' %
                    (self.dst_bucket_uri.uri, uri.bucket_name, uri.object_name))
      for file_path in self.all_src_file_paths:
        start_tmp_pos = file_path.find(self.tmpdir_prefix)
        file_path_sans_base_dir = file_path[start_tmp_pos:]
        expected.add('%sdst_subdir/%s' %
                     (self.dst_bucket_uri.uri, file_path_sans_base_dir))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testRecursiveCopyObjsAndFilesToNonExistentBucketSubDir(self):
    """Tests recursive copy of objs + files to non-existent bucket subdir"""
    # Test with and without final slash on dest subdir.
    self.RunCommand(
        'cp', ['-R', '%s' % self.src_bucket_uri.uri,
               '%s' % self.src_dir_root,
               '%sdst_subdir' % (self.dst_bucket_uri.uri)])
    actual = set(str(u) for u in self._test_wildcard_iterator(
        '%s**' % self.dst_bucket_uri.uri).IterUris())
    expected = set()
    for uri in self.all_src_obj_uris:
      expected.add('%sdst_subdir/%s' %
                  (self.dst_bucket_uri.uri, uri.object_name))
    for file_path in self.all_src_file_paths:
      start_tmp_pos = file_path.find(self.tmpdir_prefix)
      file_path_sans_base_dir = (
          file_path[start_tmp_pos:].partition(os.sep)[-1])
      expected.add('%sdst_subdir/%s' %
                   (self.dst_bucket_uri.uri, file_path_sans_base_dir))
    self.assertEqual(expected, actual)

  def testCopyingBucketSubDirToDir(self):
    """Tests copying a bucket subdir to a directory"""
    # Test with and without final slash on dest subdir.
    for (final_src_char, final_dst_char) in (
        ('', ''), ('', '/'), ('/', ''), ('/', '/') ):
      self.RunCommand(
          'cp', ['-R', '%s%s' % (self.src_bucket_subdir_uri, final_src_char),
                 '%s%s' % (self.dst_dir_root, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s/**' % self.dst_dir_root).IterUris())
      expected = set()
      for uri in self.all_src_subdir_and_below_obj_uris:
        expected.add('file://%s%s' % (self.dst_dir_root, uri.uri.partition(
            self.src_bucket_uri.uri)[-1]))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingWildcardSpecifiedBucketSubDirToExistingDir(self):
    """Tests copying a wilcard-specified bucket subdir to a directory"""
    # Test with and without final slash on dest subdir.
    for (final_src_char, final_dst_char) in (
        ('', ''), ('', '/'), ('/', ''), ('/', '/') ):
      self.RunCommand(
          'cp', ['-R',
                 '%s%s' % (self.src_bucket_subdir_uri_wildcard, final_src_char),
                 '%s%s' % (self.dst_dir_root, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s/**' % self.dst_dir_root).IterUris())
      expected = set()
      for uri in self.all_src_subdir_and_below_obj_uris:
        expected.add('file://%s%s' % (
            self.dst_dir_root, uri.uri.partition(self.src_bucket_uri.uri)[-1]))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingBucketSubDirToDirFailsWithoutMinusR(self):
    """Tests for failure when attempting bucket subdir copy without -R"""
    try:
      self.RunCommand(
          'cp', ['%s' % self.src_bucket_subdir_uri,
                 '%s' % self.dst_dir_root])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('does not exist'), -1)

  def testCopyingBucketSubDirToBucketSubDir(self):
    """Tests copying a bucket subdir to another bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_src_char, final_dst_char) in (
        ('', ''), ('', '/'), ('/', ''), ('/', '/') ):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['-R', '%s%s' % (self.src_bucket_subdir_uri, final_src_char),
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set(['%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      for uri in self.all_src_subdir_and_below_obj_uris:
        expected.add(
            '%s/%s' % (self.dst_bucket_subdir_uri.uri, uri.object_name))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testMovingBucketSubDirToNonExistentBucketSubDir(self):
    """Tests moving a bucket subdir to a non-existent bucket subdir"""
    # Test with and without final slash on dest subdir.
    for final_src_char in ('', '/'):
      self.RunCommand(
          'mv', ['%s%s' % (self.src_bucket_subdir_uri, final_src_char),
                 '%s' % (self.dst_bucket_subdir_uri.uri)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([])
      for uri in self.all_src_subdir_and_below_obj_uris:
        # Unlike the case with copying, with mv we expect renaming to occur
        # at the level of the src subdir, vs appending that subdir beneath the
        # dst subdir like is done for copying.
        expected_name = uri.object_name.replace('src_', 'dst_')
        expected.add('%s%s' % (self.dst_bucket_uri.uri, expected_name))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testMovingBucketSubDirToExistingBucketSubDir(self):
    """Tests moving a bucket subdir to a existing bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_src_char, final_dst_char) in (
        ('', ''), ('', '/'), ('/', ''), ('/', '/') ):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'mv', ['%s%s' % (self.src_bucket_subdir_uri, final_src_char),
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set(['%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      for uri in self.all_src_subdir_and_below_obj_uris:
        expected.add(
            '%s/%s' % (self.dst_bucket_subdir_uri.uri, uri.object_name))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingObjectToBucketSubDir(self):
    """Tests copying an object to a bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_dst_char) in ('', '/'):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['%sobj0' % self.src_bucket_uri,
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([
        '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri,
        '%sdst_subdir/obj0' % self.dst_bucket_uri.uri])
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingWildcardedFilesToBucketSubDir(self):
    """Tests copying wildcarded files to a bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_dst_char) in ('', '/'):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['%sf?' % self.src_dir_root,
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([
        '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri,
        '%sdst_subdir/f0' % self.dst_bucket_uri.uri,
        '%sdst_subdir/f1' % self.dst_bucket_uri.uri])
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testCopyingOneNestedFileToBucketSubDir(self):
    """Tests copying one nested file to a bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_dst_char) in ('', '/'):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'cp', ['-r', '%sdir0' % self.src_dir_root,
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([
        '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri,
        '%sdst_subdir/dir0/dir1/nested' % self.dst_bucket_uri.uri])
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testMovingWildcardedFilesToNonExistentBucketSubDir(self):
    """Tests moving files to a non-existent bucket subdir"""
    # This tests for how we allow users to do something like:
    #   gsutil cp *.txt gs://bucket/dir
    # where *.txt matches more than 1 file and gs://bucket/dir
    # doesn't exist as a subdir.
    #
    # Test with and without final slash on dest subdir.
    for (final_dst_char) in ('', '/'):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      # Copy some files into place in dst bucket.
      self.RunCommand(
          'cp', ['%sf?' % self.src_dir_root,
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      # Now do the move test.
      self.RunCommand(
          'mv', ['%s/*' % self.dst_bucket_subdir_uri.uri,
                 '%s/nonexistent/%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([
        '%sdst_subdir/nonexistent/existing_obj' % self.dst_bucket_uri.uri,
        '%sdst_subdir/nonexistent/f0' % self.dst_bucket_uri.uri,
        '%sdst_subdir/nonexistent/f1' % self.dst_bucket_uri.uri])
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testMovingObjectToBucketSubDir(self):
    """Tests moving an object to a bucket subdir"""
    # Test with and without final slash on dest subdir.
    for (final_dst_char) in ('', '/'):
      # Set up existing bucket subdir by creating an object in the subdir.
      self.RunCommand(
          'cp', ['%sf0' % self.src_dir_root,
                 '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri])
      self.RunCommand(
          'mv', ['%sobj0' % self.src_bucket_uri,
                 '%s%s' % (self.dst_bucket_subdir_uri.uri, final_dst_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([
        '%sdst_subdir/existing_obj' % self.dst_bucket_uri.uri,
        '%sdst_subdir/obj0' % self.dst_bucket_uri.uri])
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testWildcardSrcSubDirMoveDisallowed(self):
    """Tests moving a bucket subdir specified by wildcard is disallowed"""
    try:
      self.RunCommand(
          'mv', ['%s*' % self.src_bucket_subdir_uri,
                 '%s' % self.dst_bucket_subdir_uri.uri])
      self.fail('Did not get expected CommandException')
    except CommandException, e:
      self.assertNotEqual(e.reason.find('mv command disallows naming'), -1)

  def testMovingBucketNestedSubDirToBucketNestedSubDir(self):
    """Tests moving a bucket nested subdir to another bucket nested subdir"""
    # Test with and without final slash on dest subdir.
    for final_src_char in ('', '/'):
      self.RunCommand(
          'mv', ['%s%s' % (self.src_bucket_subdir_uri, final_src_char),
                 '%s' % (self.dst_bucket_subdir_uri.uri)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_subdir_uri.uri).IterUris())
      expected = set([])
      for uri in self.all_src_subdir_and_below_obj_uris:
        # Unlike the case with copying, with mv we expect renaming to occur
        # at the level of the src subdir, vs appending that subdir beneath the
        # dst subdir like is done for copying.
        expected_name = uri.object_name.replace('src_', 'dst_')
        expected.add('%s%s' % (self.dst_bucket_uri, expected_name))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testRemovingBucketSubDir(self):
    """Tests removing a bucket subdir"""
    # Test with and without final slash on dest subdir.
    for final_src_char in ('', '/'):
      # Setup: Copy a directory, including subdir, to bucket.
      self.RunCommand('cp', ['-R', self.src_dir_root, self.dst_bucket_uri.uri])
      src_subdir = self.src_dir_root.split(os.path.sep)[-2]
      # Test removing bucket subdir.
      self.RunCommand(
          'rm', ['-R', '%s%s/dir0%s' %
                       (self.dst_bucket_uri, src_subdir, final_src_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s**' % self.dst_bucket_uri.uri).IterUris())
      expected = set()
      for fname in self.non_nested_file_names:
        expected.add('%s%s/%s' % (self.dst_bucket_uri.uri, src_subdir, fname))
      self.assertEqual(expected, actual)
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def testRecursiveRemoveObjsInBucket(self):
    """Tests removing all objects in bucket via rm -R gs://bucket"""
    # Test with and without final slash on dest subdir.
    for final_src_char in ('', '/'):
      # Setup: Copy a directory, including subdir, to bucket.
      self.RunCommand('cp', ['-R', self.src_dir_root, self.dst_bucket_uri.uri])
      # Test removing all objects via rm -R.
      self.RunCommand('rm', ['-R', '%s%s' % (self.dst_bucket_uri,
                                             final_src_char)])
      actual = set(str(u) for u in self._test_wildcard_iterator(
          '%s*' % self.dst_bucket_uri.uri).IterUris())
      self.assertEqual(0, len(actual))
      # Clean up/re-set up for next variant iteration.
      self.tearDownClass()
      self.setUpClass()

  def FinalObjNameComponent(self, uri):
    """For gs://bucket/abc/def/ghi returns ghi."""
    return uri.uri.rpartition('/')[-1]