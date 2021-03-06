# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2012-2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Utilities with minimum-depends for use in setup.py
"""

import email
import os
import re
import StringIO
import subprocess
import sys

from distutils.command import install as du_install
from distutils import log
from setuptools.command import install
from setuptools.command import sdist

log.set_verbosity(log.INFO)
TRUE_VALUES = ['true', '1', 'yes']


def _parse_mailmap(mailmap_info):
    mapping = dict()
    for l in mailmap_info:
        try:
            canonical_email, alias = re.match(
                r'[^#]*?(<.+>).*(<.+>).*', l).groups()
        except AttributeError:
            continue
        mapping[alias] = canonical_email
    return mapping


def read_git_mailmap(git_dir, mailmap='.mailmap'):
    mailmap = os.path.join(git_dir, mailmap)
    if os.path.exists(mailmap):
        return _parse_mailmap(open(mailmap, 'r').readlines())
    return dict()


def canonicalize_emails(changelog, mapping):
    """Takes in a string and an email alias mapping and replaces all
       instances of the aliases in the string with their real email.
    """
    for alias, email_address in mapping.iteritems():
        changelog = changelog.replace(alias, email_address)
    return changelog


# Get requirements from the first file that exists
def get_reqs_from_files(requirements_files):
    for requirements_file in requirements_files:
        if os.path.exists(requirements_file):
            with open(requirements_file, 'r') as fil:
                return fil.read().split('\n')
    return []


def parse_requirements(requirements_files=['requirements.txt',
                                           'tools/pip-requires']):
    requirements = []
    for line in get_reqs_from_files(requirements_files):
        # For the requirements list, we need to inject only the portion
        # after egg= so that distutils knows the package it's looking for
        # such as:
        # -e git://github.com/openstack/nova/master#egg=nova
        if re.match(r'\s*-e\s+', line):
            requirements.append(re.sub(r'\s*-e\s+.*#egg=(.*)$', r'\1',
                                line))
        # such as:
        # http://github.com/openstack/nova/zipball/master#egg=nova
        elif re.match(r'\s*https?:', line):
            requirements.append(re.sub(r'\s*https?:.*#egg=(.*)$', r'\1',
                                line))
        # -f lines are for index locations, and don't get used here
        elif re.match(r'\s*-f\s+', line):
            pass
        # argparse is part of the standard library starting with 2.7
        # adding it to the requirements list screws distro installs
        elif line == 'argparse' and sys.version_info >= (2, 7):
            pass
        else:
            requirements.append(line)

    return requirements


def parse_dependency_links(requirements_files=['requirements.txt',
                                               'tools/pip-requires']):
    dependency_links = []
    # dependency_links inject alternate locations to find packages listed
    # in requirements
    for line in get_reqs_from_files(requirements_files):
        # skip comments and blank lines
        if re.match(r'(\s*#)|(\s*$)', line):
            continue
        # lines with -e or -f need the whole line, minus the flag
        if re.match(r'\s*-[ef]\s+', line):
            dependency_links.append(re.sub(r'\s*-[ef]\s+', '', line))
        # lines that are only urls can go in unmolested
        elif re.match(r'\s*https?:', line):
            dependency_links.append(line)
    return dependency_links


def _run_shell_command(cmd, throw_on_error=False):
    if os.name == 'nt':
        output = subprocess.Popen(["cmd.exe", "/C", cmd],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
    else:
        output = subprocess.Popen(["/bin/sh", "-c", cmd],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
    out = output.communicate()
    if output.returncode and throw_on_error:
        raise Exception("%s returned %d" % cmd, output.returncode)
    if len(out) == 0:
        return None
    if len(out[0].strip()) == 0:
        return None
    return out[0].strip()


def _get_git_directory():
    parent_dir = os.path.dirname(os.curdir)
    while True:
        git_dir = os.path.join(parent_dir, '.git')
        if os.path.exists(git_dir):
            return git_dir
        parent_dir, child = os.path.split(parent_dir)
        if not child:   # reached to root dir
            return None


def get_boolean_option(option_dict, option_name, env_name):
    return ((option_name in option_dict
             and option_dict[option_name].lower() in TRUE_VALUES) or
            str(os.getenv(env_name)).lower() in TRUE_VALUES)


def write_git_changelog(git_dir=None, dest_dir=os.path.curdir,
                        option_dict=dict()):
    """Write a changelog based on the git changelog."""
    should_skip = get_boolean_option(option_dict, 'skip_changelog',
                                     'SKIP_WRITE_GIT_CHANGELOG')
    if not should_skip:
        log.info('[pbr] Writing ChangeLog')
        new_changelog = os.path.join(dest_dir, 'ChangeLog')
        if git_dir is None:
            git_dir = _get_git_directory()
        if git_dir:
            git_log_cmd = 'git --git-dir=%s log' % git_dir
            changelog = _run_shell_command(git_log_cmd)
            mailmap = read_git_mailmap(git_dir)
            with open(new_changelog, "w") as changelog_file:
                changelog_file.write(canonicalize_emails(changelog, mailmap))


def generate_authors(git_dir=None, dest_dir='.', option_dict=dict()):
    """Create AUTHORS file using git commits."""
    should_skip = get_boolean_option(option_dict, 'skip_authors',
                                     'SKIP_GENERATE_AUTHORS')
    if not should_skip:
        log.info('[pbr] Generating AUTHORS')
        jenkins_email = 'jenkins@review'
        old_authors = os.path.join(dest_dir, 'AUTHORS.in')
        new_authors = os.path.join(dest_dir, 'AUTHORS')
        if git_dir is None:
            git_dir = _get_git_directory()
        if git_dir:
            # don't include jenkins email address in AUTHORS file
            git_log_cmd = ("git --git-dir=" + git_dir +
                           " log --format='%aN <%aE>' | sort -u | "
                           "egrep -v '" + jenkins_email + "'")
            changelog = _run_shell_command(git_log_cmd)
            signed_cmd = ("git log --git-dir=" + git_dir +
                          " | grep -i Co-authored-by: | sort -u")
            signed_entries = _run_shell_command(signed_cmd)
            if signed_entries:
                new_entries = "\n".join(
                    [signed.split(":", 1)[1].strip()
                     for signed in signed_entries.split("\n") if signed])
                changelog = "\n".join((changelog, new_entries))

            mailmap = read_git_mailmap(git_dir)
            with open(new_authors, 'w') as new_authors_fh:
                new_authors_fh.write(canonicalize_emails(changelog, mailmap))
                if os.path.exists(old_authors):
                    with open(old_authors, "r") as old_authors_fh:
                        new_authors_fh.write('\n' + old_authors_fh.read())


_rst_template = """%(heading)s
%(underline)s

.. automodule:: %(module)s
  :members:
  :undoc-members:
  :show-inheritance:
"""


def _find_modules(arg, dirname, files):
    for filename in files:
        if filename.endswith('.py') and filename != '__init__.py':
            arg["%s.%s" % (dirname.replace('/', '.'),
                           filename[:-3])] = True


class DistutilsInstall(install.install):
    """Forces single-version-externally-managed."""

    command_name = 'install'

    def run(self):
        return du_install.install.run(self)


class LocalSDist(sdist.sdist):
    """Builds the ChangeLog and Authors files from VC first."""

    command_name = 'sdist'

    def run(self):
        option_dict = self.distribution.get_option_dict('pbr')
        write_git_changelog(option_dict=option_dict)
        generate_authors(option_dict=option_dict)
        # sdist.sdist is an old style class, can't use super()
        sdist.sdist.run(self)

try:
    from sphinx import application
    from sphinx import config
    from sphinx import setup_command

    class LocalBuildDoc(setup_command.BuildDoc):

        command_name = 'build_sphinx'
        builders = ['html', 'man']

        def generate_autoindex(self):
            option_dict = self.distribution.get_option_dict('build_sphinx')
            log.info("[pbr] Autodocumenting from %s"
                     % os.path.abspath(os.curdir))
            modules = {}
            if 'source_dir' in option_dict:
                source_dir = os.path.join(option_dict['source_dir'][1], 'api')
            else:
                source_dir = 'doc/source/api'
            if not os.path.exists(source_dir):
                os.makedirs(source_dir)
            for pkg in self.distribution.packages:
                if '.' not in pkg:
                    os.path.walk(pkg, _find_modules, modules)
            module_list = modules.keys()
            module_list.sort()
            autoindex_filename = os.path.join(source_dir, 'autoindex.rst')
            with open(autoindex_filename, 'w') as autoindex:
                autoindex.write(""".. toctree::
    :maxdepth: 1

    """)
                for module in module_list:
                    output_filename = os.path.join(source_dir,
                                                   "%s.rst" % module)
                    heading = "The :mod:`%s` Module" % module
                    underline = "=" * len(heading)
                    values = dict(module=module, heading=heading,
                                  underline=underline)

                    log.info("[pbr] Generating %s"
                             % output_filename)
                    with open(output_filename, 'w') as output_file:
                        output_file.write(_rst_template % values)
                    autoindex.write("   %s.rst\n" % module)

        def _sphinx_run(self):
            if not self.verbose:
                status_stream = StringIO.StringIO()
            else:
                status_stream = sys.stdout
            confoverrides = {}
            if self.version:
                confoverrides['version'] = self.version
            if self.release:
                confoverrides['release'] = self.release
            if self.today:
                confoverrides['today'] = self.today
            sphinx_config = config.Config(self.config_dir, 'conf.py', {}, [])
            if self.builder == 'man' and len(sphinx_config.man_pages) == 0:
                return
            app = application.Sphinx(
                self.source_dir, self.config_dir,
                self.builder_target_dir, self.doctree_dir,
                self.builder, confoverrides, status_stream,
                freshenv=self.fresh_env, warningiserror=True)

            try:
                app.build(force_all=self.all_files)
            except Exception, err:
                from docutils import utils
                if isinstance(err, utils.SystemMessage):
                    sys.stder.write('reST markup error:\n')
                    sys.stderr.write(err.args[0].encode('ascii',
                                                        'backslashreplace'))
                    sys.stderr.write('\n')
                else:
                    raise

            if self.link_index:
                src = app.config.master_doc + app.builder.out_suffix
                dst = app.builder.get_outfilename('index')
                os.symlink(src, dst)

        def run(self):
            option_dict = self.distribution.get_option_dict('pbr')
            if ('autodoc_index_modules' in option_dict and
                    option_dict.get(
                        'autodoc_index_modules').lower() in TRUE_VALUES and
                    not os.getenv('SPHINX_DEBUG')):
                self.generate_autoindex()

            for builder in self.builders:
                self.builder = builder
                self.finalize_options()
                self.project = self.distribution.get_name()
                self.version = self.distribution.get_version()
                self.release = self.distribution.get_version()
                if 'warnerrors' in option_dict:
                    self._sphinx_run()
                else:
                    setup_command.BuildDoc.run(self)

    class LocalBuildLatex(LocalBuildDoc):
        builders = ['latex']
        command_name = 'build_sphinx_latex'

    _have_sphinx = True

except ImportError:
    _have_sphinx = False


def have_sphinx():
    return _have_sphinx


def _get_revno(git_dir):
    """Return the number of commits since the most recent tag.

    We use git-describe to find this out, but if there are no
    tags then we fall back to counting commits since the beginning
    of time.
    """
    describe = _run_shell_command(
        "git --git-dir=%s describe --always" % git_dir)
    if "-" in describe:
        return describe.rsplit("-", 2)[-2]

    # no tags found
    revlist = _run_shell_command(
        "git --git-dir=%s rev-list --abbrev-commit HEAD" % git_dir)
    return len(revlist.splitlines())


def _get_version_from_git(pre_version):
    """Return a version which is equal to the tag that's on the current
    revision if there is one, or tag plus number of additional revisions
    if the current revision has no tag.
    """

    git_dir = _get_git_directory()
    if git_dir:
        if pre_version:
            try:
                return _run_shell_command(
                    "git --git-dir=" + git_dir + " describe --exact-match",
                    throw_on_error=True).replace('-', '.')
            except Exception:
                sha = _run_shell_command(
                    "git --git-dir=" + git_dir + " log -n1 --pretty=format:%h")
                return "%s.a%s.g%s" % (pre_version, _get_revno(git_dir), sha)
        else:
            return _run_shell_command(
                "git --git-dir=" + git_dir + " describe --always").replace(
                    '-', '.')
    return None


def _get_version_from_pkg_info(package_name):
    """Get the version from PKG-INFO file if we can."""
    try:
        pkg_info_file = open('PKG-INFO', 'r')
    except (IOError, OSError):
        return None
    try:
        pkg_info = email.message_from_file(pkg_info_file)
    except email.MessageError:
        return None
    # Check to make sure we're in our own dir
    if pkg_info.get('Name', None) != package_name:
        return None
    return pkg_info.get('Version', None)


def get_version(package_name, pre_version=None):
    """Get the version of the project. First, try getting it from PKG-INFO, if
    it exists. If it does, that means we're in a distribution tarball or that
    install has happened. Otherwise, if there is no PKG-INFO file, pull the
    version from git.

    We do not support setup.py version sanity in git archive tarballs, nor do
    we support packagers directly sucking our git repo into theirs. We expect
    that a source tarball be made from our git repo - or that if someone wants
    to make a source tarball from a fork of our repo with additional tags in it
    that they understand and desire the results of doing that.
    """
    version = os.environ.get("OSLO_PACKAGE_VERSION", None)
    if version:
        return version
    version = _get_version_from_pkg_info(package_name)
    if version:
        return version
    version = _get_version_from_git(pre_version)
    if version:
        return version
    raise Exception("Versioning for this project requires either an sdist"
                    " tarball, or access to an upstream git repository.")


def get_manpath():
    manpath = 'share/man'
    if os.path.exists(os.path.join(sys.prefix, 'man')):
        # This works around a bug with install where it expects every node
        # in the relative data directory to be an actual directory, since at
        # least Debian derivatives (and probably other platforms as well)
        # like to symlink Unixish /usr/local/man to /usr/local/share/man.
        manpath = 'man'
    return manpath
