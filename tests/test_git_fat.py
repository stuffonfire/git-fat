import os
import sys
import shutil
import subprocess as sub
import tempfile
import unittest
import logging as _logging  # Use logger.error(), not logging.error()
import time
import stat
import platform
import re
import hashlib

_logging.basicConfig(format='%(levelname)s:%(filename)s: %(message)s')
logger = _logging.getLogger(__name__)


def get_log_level(log_level_string):
    log_level_string = log_level_string.lower()
    if not log_level_string:
        return _logging.WARNING
    levels = {'debug': _logging.DEBUG,
              'info': _logging.INFO,
              'warning': _logging.WARNING,
              'error': _logging.ERROR,
              'critical': _logging.CRITICAL}
    if log_level_string in levels:
        return levels[log_level_string]
    else:
        logger.warning("Invalid log level: {}".format(log_level_string))
    return _logging.WARNING


GIT_FAT_LOG_LEVEL = get_log_level(os.getenv("GIT_FAT_LOG_LEVEL", ""))
GIT_FAT_LOG_FILE = os.getenv("GIT_FAT_LOG_FILE", "")
GIT_FAT_TEST_PRODUCTION = False
GIT_FAT_KEEP_TEMP_DIRS = False
GIT_FAT_DISABLE_COVERAGE = False

if os.getenv("GIT_FAT_TEST_PRODUCTION") == "1":
    GIT_FAT_TEST_PRODUCTION = True
if os.getenv("GIT_FAT_KEEP_TEMP_DIRS") == "1":
    GIT_FAT_KEEP_TEMP_DIRS = True
if os.getenv("GIT_FAT_DISABLE_COVERAGE") == "1":
    GIT_FAT_DISABLE_COVERAGE = True

ignore_errors_in_log_file = []


def check_log_file_for_errors():
    """ If --failfast option was specified (to stop on first error),
    then this function will ensure that stop happens.

    When git-fat is launched as a sub-subprocess by the git subprocess
    and it fails, then the tests won't know that. The log file needs
    to be checked for lines starting with "ERROR", "WARNING"
    or "CRITICAL". The log file is checked every time there is a new
    subprocess to be created when executing the call() function.

    To ignore specific errors (expected by test) append
    them to the "ignore_errors_in_log_file" global list. If error is
    expected to occur twice, then append it twice.

    Make sure that the log file is deleted each time before running tests
    (the run_tests_isolated.bat script on Windows does it automatically).
    """
    log_file = GIT_FAT_LOG_FILE
    if log_file and "--failfast" in sys.argv:
        sys.stdout.flush()
        sys.stderr.flush()
    if ("--failfast" not in sys.argv
            or not log_file
            or not os.path.exists(log_file)):
        return False
    ignore_errors = list(ignore_errors_in_log_file)  # Make a copy
    with open(log_file, "rU") as fo:
        errors = []
        for line in fo:
            # Only one \n to remove. Keep original lines returned
            # by commands.
            line = re.sub(r"\n$", "", line)
            # Include any subsequent lines after error up to 10
            if re.search(r"^\s*(ERROR|WARNING|CRITICAL)", line):
                for ignore_error in ignore_errors:
                    if ignore_error in line:
                        logger.info("Ignoring error: {}".format(line))
                        # Remove only one occurence
                        ignore_errors.remove(ignore_error)
                        break
                    else:
                        errors.append(line)
                        break
                else:
                    errors.append(line)
            elif len(errors):
                errors.append(line)
            if len(errors) >= 10:
                errors.append("...")
                break
        if len(errors):
            hr1 = "=" * 80 + "\n"
            hr2 = "-" * 80 + "\n"
            errormsg = "\n".join(errors) + "\n"
            logger.error("\n\n{}ERROR: Found errors in the log file ({}):\n"
                         "{}{}{}".format(hr1, os.path.basename(log_file),
                                         hr2, errormsg, hr2))
            sys.exit(1)


def call(cmd, *args, **kwargs):
    if isinstance(cmd, str):
        cmd = cmd.split()
    check_log_file_for_errors()
    ignore_error_codes = []
    logger.debug('{}'.format(' '.join(cmd)) + ' ()'.format(args, kwargs))
    if "ignore_error_codes" in kwargs:
        ignore_error_codes = kwargs.pop("ignore_error_codes")
    try:
        output = sub.check_output(cmd, *args, **kwargs)
    except sub.CalledProcessError as e:
        if ignore_error_codes and e.returncode in ignore_error_codes:
            return e.output
        logger.error('Command `{}` returned code {}'
                     .format(' '.join(cmd), e.returncode))
        logger.error("The output of the command was: {}".format(e.output))
        raise
    return output


def git(cliargs, *args, **kwargs):
    if isinstance(cliargs, str):
        cliargs = cliargs.split()
    cmd = ['git'] + cliargs
    return call(cmd, *args, **kwargs)


def commit(message):
    git('add -A')
    git(['commit', '-m', message])


def read_index(filename):
    objhash = git(['hash-object', filename]).strip()
    contents = git(['cat-file', '-p', objhash])
    return contents

def sha1(fpath):
    h = hashlib.sha1()
    with open(fpath) as f:
        h.update(f.read())
    return h.hexdigest()    


# -----------------------------------------------------------------------------
# On Windows files may be read only and may require changing
# permissions. Always use these functions for moving/deleting
# files or dirs.
#
# In unit tests there are issues only when deleting the whole
# git repository temp directory. When moving or deleting single
# files there are no problems currrently, but let's use the same
# functions as in git_fat.py to be consistent and avoid any issues
# in the future.

def move_file(src, dst):
    if platform.system() == "Windows":
        if os.path.exists(src) and not os.access(src, os.W_OK):
            st = os.stat(src)
            os.chmod(src, st.st_mode | stat.S_IWUSR)
        if os.path.exists(dst) and not os.access(dst, os.W_OK):
            st = os.stat(dst)
            os.chmod(dst, st.st_mode | stat.S_IWUSR)
    shutil.move(src, dst)


def delete_file(f):
    if platform.system() == "Windows":
        if os.path.exists(f) and not os.access(f, os.W_OK):
            st = os.stat(f)
            os.chmod(f, st.st_mode | stat.S_IWUSR)
    os.remove(f)


def delete_directory(d):
    if not GIT_FAT_KEEP_TEMP_DIRS:
        shutil.rmtree(d, ignore_errors=False, onerror=_delete_onerror)


def _delete_onerror(func, path, unused_exc_info):
    # This handler fixes errors on Windows when deleting the git
    # repository along with the .git/ subdirectory which is set
    # to read only mode.
    # >> WindowsError: [Error 5] Access is denied:
    # >> 'c:\\users\\user\\appdata\\local\\temp\\gitutils\\.git\\objects
    # >>     \\pack\\pack-1b2b45afb56aceb92531ff083873d2ef27595b26.idx'
    if platform.system() == "Windows" and not os.access(path, os.W_OK):
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IWUSR)
        func(path)
    else:
        raise

# -----------------------------------------------------------------------------


class Base(unittest.TestCase):

    def setUp(self):
        """ Get me into an initialized git directory! """
        logger.info("************ {}.{} ************"
                    .format(self.__class__.__name__, self._testMethodName))

        self.templatedir = self._unset_templatedir()

        if not GIT_FAT_TEST_PRODUCTION:
            # Configure path to use development git-fat binary script
            test_dir = os.path.dirname(os.path.realpath(__file__))
            self.oldpath = os.environ["PATH"]
            sep = ';' if platform.system() == "Windows" else ':'
            if platform.system() == "Windows":
                win32_dir = os.path.normpath(test_dir + "/../win32")
                # Replace shebang in the git-fat script
                self.gitfat_script = os.path.join(test_dir, 'git-fat')
                self._replace_in_file(self.gitfat_script,
                                      '#!/usr/bin/env python',
                                      '#!{}'.format(sys.executable))
                os.environ["PATH"] = sep.join([test_dir, win32_dir]
                                              + self.oldpath.split(sep))
            else:
                os.environ["PATH"] = sep.join([test_dir]
                                              + self.oldpath.split(sep))

        self.olddir = os.getcwd()

        # Can't test in the repo
        # Easiest way is to do it in temp dir
        self.tempdir = tempfile.mkdtemp(prefix='git-fat-test')
        logger.info("tempdir: {}".format(self.tempdir))

        os.chdir(self.tempdir)

        self.fatstore = os.path.join(self.tempdir, 'fat-store')
        os.mkdir(self.fatstore)

        self.repo = os.path.join(self.tempdir, 'fat-test1')
        git(['init', self.repo])
        os.chdir(self.repo)

    def tearDown(self):
        if self.templatedir:
            self._restore_templatedir(self.templatedir)
        if not GIT_FAT_DISABLE_COVERAGE:
            call('coverage combine')
            # Copy .coverage files to the .coverage/ subdirectory
            coverage_dir = os.path.join(self.olddir, ".coverage")
            if not os.path.exists(coverage_dir):
                os.mkdir(coverage_dir)
            move_file(os.path.join(self.repo, '.coverage'),
                      os.path.join(coverage_dir, '.coverage.{}'.format(time.time())))
        os.chdir(self.olddir)
        delete_directory(self.tempdir)
        if not GIT_FAT_TEST_PRODUCTION:
            os.environ["PATH"] = self.oldpath
            if platform.system() == "Windows":
                # Replace shebang in the git-fat script
                self._replace_in_file(self.gitfat_script,
                                      '#!{}'.format(sys.executable),
                                      '#!/usr/bin/env python')

    def _setup_gitfat_files(self):
        with open('.gitfat', 'wb') as f:
            f.write('[copy]\nremote={}'.format(self.fatstore))
        with open('.gitattributes', 'wb') as f:
            f.write('*.fat filter=fat -crlf')

    def _replace_in_file(self, f, search, replace):
        with open(f, "rb") as fo:
            contents = fo.read()
        contents = contents.replace(search, replace)
        with open(f, "wb") as fo:
            fo.write(contents)

    def _unset_templatedir(self):
        # Unset the git template dir if set globally.
        # Return code may be "1" when option is not set in .gitconfig.
        # Output will contain new line
        templatedir = call("git config --global init.templatedir",
                           ignore_error_codes=[1]).strip()
        if templatedir:
            logger.info("Detected git global init.templatedir ({}), disabling it "
                        "temporarily".format(templatedir))
            call("git config --global init.templatedir".split() + [""])
            return templatedir

    def _restore_templatedir(self, templatedir):
        if not templatedir:
            return
        logger.info("Restoring git global init.templatedir: {}"
                    .format(templatedir))
        call("git config --global init.templatedir".split()
             + [templatedir])


class InitTestCase(Base):
    """ Test cases which have not had git-fat initalized yet """

    def test_git_fat_init(self):
        with open('.gitfat', 'wb') as f:
            f.write('[copy]\nremote={}'.format(self.fatstore))
        out = git('fat init')
        expect = 'Setting filters in .git/config\nCreating .git/fat/objects\nInitialized git-fat'.strip()
        self.assertEqual(out.strip(), expect)
        self.assertTrue(os.path.isdir('.git/fat/objects'))

        out = git('config filter.fat.clean')
        self.assertEqual(out.strip(), 'git-fatclean %f')

        out = git('config filter.fat.smudge')
        self.assertEqual(out.strip(), 'git-fatsmudge %f')

    def test_git_fat_no_dotgitfat(self):
        logger.info("The next warning from the log file, with message about "
                    "'Missing config' will be ignored. It is expected to "
                    "happen as part of the test.")
        ignore_errors_in_log_file.append("Missing config")
        out = git('fat push', stderr=sub.STDOUT)
        self.assertTrue("Missing config" in out)
        self.assertTrue("does not appear" in out)

    def test_command_not_push(self):
        """ Test that find works without a backend """
        filename = 'somebin.png'
        with open(filename, 'wb') as f:
            f.write('aa' * 9990)
        commit('add file')
        out = git('fat find 9000', stderr=sub.STDOUT)
        self.assertTrue('somebin.png' in out)


class InitRepoTestCase(Base):

    def setUp(self):
        super(InitRepoTestCase, self).setUp()

        self._setup_gitfat_files()
        git('fat init')
        commit('initial')


class FileTypeTestCase(InitRepoTestCase):

    def test_symlink_74bytes(self):
        """ Verify symlinks which match magiclen don't get converted """
        # os.symlink() is available only on Unix
        if "symlink" not in dir(os):
            self.assertTrue(True)
            return
        # Create broken symlink
        # is exactly 74 bytes, the magic length
        os.symlink(  # pylint: disable=no-member
            '/oe/dss-oe/dss-add-ons-testing-build/deploy/licenses/'
            'common-licenses/GPL-3', 'c.fat')
        git('add c.fat')
        git('commit -m"added_symlink"')
        self.assertTrue(os.path.islink('c.fat'))

    def test_file_with_spaces(self):
        """ Ensure that files with spaces don't make git-fat barf """
        contents = 'This is a fat file\n'
        filename = 'A fat file with spaces.fat'
        with open(filename, 'wb') as f:
            f.write(contents)
        commit("Nobody expects a space inafilename")
        self.assertTrue('#$# git-fat ' in read_index(filename))

class AddNewObjectTestCase(InitRepoTestCase):

    
    def test_add_new_object(self):
        digest = 'f0a40e80bfc8a98f5f8f78e2f532bfd2b7d3d937'
        fpath = os.path.join(os.getcwd(), '.git/fat/objects', digest)
        self.assertFalse(os.path.exists(fpath))

        FNULL = open(os.devnull, 'w')
        sub.check_call(['dd','if=/dev/zero','of=testfile.fat','bs=1024','count=5000'],
                       stdout=FNULL, stderr=FNULL)

        git('add testfile.fat')

        self.assertTrue(os.path.exists(fpath))
        self.assertEqual(
            '#$# git-fat f0a40e80bfc8a98f5f8f78e2f532bfd2b7d3d937              5120000\n',
            read_index('testfile.fat')
        )
        self.assertEqual(sha1(fpath), digest)


class FastFilterCommandsTestCase(InitRepoTestCase):
    def test_fast_filter_commands(self):

        # start with fast
        git('fat fast-filters')
        out = git('config filter.fat.clean')
        self.assertEqual(out.strip(), 'git-fatclean %f')        

        out = git('config filter.fat.smudge')
        self.assertEqual(out.strip(), 'git-fatsmudge %f')        


        # try with regular
        git('fat regular-filters')
        out = git('config filter.fat.clean')
        self.assertEqual(out.strip(), 'git-fat filter-clean %f')        

        out = git('config filter.fat.smudge')
        self.assertEqual(out.strip(), 'git-fat filter-smudge %f')        

        # try fast again
        git('fat fast-filters')
        out = git('config filter.fat.clean')
        self.assertEqual(out.strip(), 'git-fatclean %f')        

        out = git('config filter.fat.smudge')
        self.assertEqual(out.strip(), 'git-fatsmudge %f')

class GeneralTestCase(InitRepoTestCase):

    def setUp(self):
        super(GeneralTestCase, self).setUp()

        filename = 'a.fat'
        contents = 'a'
        with open(filename, 'wb') as f:
            f.write(contents * 1024)
        filename = 'b.fat'
        with open(filename, 'wb') as f:
            f.write(contents * 1024 * 1024)
        filename = 'c d e.fat'
        with open(filename, 'wb') as f:
            f.write(contents * 2048 * 1024)
        commit("add fatfiles")

    def test_status(self):
        out = git('fat status')
        self.assertEqual(out, '')
        objhash = read_index('b.fat').split()[2]
        path = os.path.join(os.getcwd(), '.git/fat/objects', objhash)
        move_file(path, os.path.join(self.tempdir, objhash))
        delete_file('b.fat')

        # Need to checkout the file again so that it can be re-smudged
        git('checkout b.fat')

        # get the hash
        out = git('fat status')
        self.assertTrue('Orphan' in out)
        self.assertTrue(objhash in out)

        # Remove the file again
        delete_file('b.fat')
        # commit this time
        commit('remove file')

        move_file(os.path.join(self.tempdir, objhash), path)
        # get the hash
        out = git('fat status')
        self.assertTrue('Stale' in out)
        self.assertTrue(objhash in out)

    def test_list(self):
        files = ('a.fat', 'b.fat', 'c d e.fat')
        hashes = {f: read_index(f).split()[2] for f in files}

        out = git('fat list')
        lines = out.splitlines()[:-1]  # ignore trailing newline
        for line in lines:
            objhash, filename = line.split(' ', 1)
            self.assertEqual(hashes[filename], objhash)

    def test_find(self):
        contents = 'b'

        filename = 'small.sh'
        with open(filename, 'wb') as f:
            f.write(contents * 9990)
        # make sure they don't match our filter first
        filename = 'b.notfat'
        with open(filename, 'wb') as f:
            f.write(contents * 1024 * 1024)
        filename = 'c d e.notfat'
        with open(filename, 'wb') as f:
            f.write(contents * 2048 * 1024)
        commit('oops, added files not matching .gitattributes')
        out = git('fat find 10000')
        self.assertTrue('b.notfat' in out)
        self.assertTrue('c d e.notfat' in out)
        self.assertTrue('small.sh' not in out)

    def test_index_filter(self):

        flowerpot = 'flowerpot.tar.gz'
        with open(flowerpot, 'wb') as f:
            f.write('a' * 9990)
        commit('add fake tar file')
        whale = 'whale.tar.gz'
        with open(whale, 'wb') as f:
            f.write('a' * 10000)
        commit('add another fake tar file')
        out = git('fat find 9000')
        self.assertTrue(whale in out)
        self.assertTrue(flowerpot in out)

        fd, filename = tempfile.mkstemp()
        with os.fdopen(fd, 'wb') as f:
            f.write(flowerpot + '\n')
            f.write(whale + '\n')

        # Need to replace backslashes with slashes, otherwise command
        # fails on Windows.
        filename = filename.replace("\\", "/")
        git(['filter-branch', '--index-filter',
             'git fat index-filter {}'.format(filename),
             '--tag-name-filter', 'cat', '--', '--all'])

        self.assertTrue('#$# git-fat' in read_index(flowerpot))
        self.assertTrue('#$# git-fat' in read_index(whale))
        self.assertTrue(flowerpot in read_index('.gitattributes'))
        self.assertTrue(flowerpot in read_index('.gitattributes'))

        delete_file(filename)


class FastSmudgeTestCase(InitRepoTestCase):

    def setUp(self):
        super(FastSmudgeTestCase, self).setUp()

        filename = 'a.fat'
        contents = 'a'
        with open(filename, 'wb') as f:
            f.write(contents * 1024)
        filename = 'b.fat'
        with open(filename, 'wb') as f:
            f.write(contents * 1024 * 1024)
        filename = 'c d e.fat'
        with open(filename, 'wb') as f:
            f.write(contents * 2048 * 1024)
        commit("add fatfiles")


    def test_smudge(self):
        test_files = [
            'a.fat',
            'b.fat',
            'c d e.fat'
        ]
        for fname in test_files:
            digest = sha1(fname)
            gitdir = os.path.join(os.getcwd(), '.git')
            fpath = os.path.join(gitdir, 'fat', 'objects', digest)
            self.assertTrue(os.path.exists(fpath))

            findex = read_index(fname)

            with open(fpath) as f:
                fcontents = f.read()

            cleanp = sub.Popen(['git', 'fatsmudge', fname],stdin=sub.PIPE, stdout=sub.PIPE, env={'GIT_DIR': gitdir})
            out, _ = cleanp.communicate(findex)
            
            self.assertEquals(fcontents, out)

            # make sure things work even when git fat file doesn't exist
            os.remove(fpath)
            cleanp = sub.Popen(['git', 'fatsmudge', fname],stdin=sub.PIPE, stdout=sub.PIPE, env={'GIT_DIR': gitdir})
            out, _ = cleanp.communicate(findex)

            self.assertEquals(findex, out)



if __name__ == "__main__":
    if GIT_FAT_LOG_LEVEL:
        logger.setLevel(GIT_FAT_LOG_LEVEL)
    if GIT_FAT_LOG_FILE:
        file_handler = _logging.FileHandler(GIT_FAT_LOG_FILE)
        file_handler.setLevel(GIT_FAT_LOG_LEVEL)
        formatter = _logging.Formatter('%(levelname)s:%(filename)s: %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    unittest.main()
