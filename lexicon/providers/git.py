"""Provider which uses text files in a Git repository."""
import logging
import os.path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Union

import dns.zone

try:
    import git
except ImportError:
    pass

from lexicon.exceptions import AuthenticationError
from lexicon.providers.localzone import Provider as LocalzoneProvider

LOGGER = logging.getLogger(__name__)

NAMESERVER_DOMAINS = []


def provider_parser(subparser):
    """Return the parser for this provider."""
    subparser.add_argument(
        "--git-repo",
        help="Path or URL of Git repository containing zone files",
    )
    subparser.add_argument(
        "--git-path",
        help="Path to zone files, relative to root of repo. {domain} will be substituted, if present.",
    )
    subparser.add_argument(
        "--git-branch",
        help="Remote repository branch to pull (and possibly push).",
    )
    subparser.add_argument(
        "--git-push-branch",
        help="Remote repository branch to push, if different than pull.",
    )
    subparser.add_argument(
        "--git-message",
        help="Commit message template. {domain} will be substituted, if present.",
    )


def _clone(from_url: str, to_path: str, **kwargs) -> git.Repo:
    return git.Repo.clone_from(from_url, to_path, **kwargs)


def _push(repo: git.Repo, **kwargs) -> bool:
    push_info = repo.remote().push()[0]
    if push_info.flags & push_info.ERROR == push_info.ERROR:
        prefix = 'Error pushing, got'
        level = logging.ERROR
        result = False
    else:
        prefix = 'Pushed with'
        level = logging.INFO
        result = True
    LOGGER.log(level, '%s bitflags %d: %s', prefix, push_info.flags, push_info.summary.strip())
    return result


class Provider(LocalzoneProvider):
    """Provider which reads and writes text files in a Git repository."""

    def __init__(self, config):
        super(Provider, self).__init__(config)
        self.temp_dir: TemporaryDirectory = None
        self.repo: git.Repo = None

    def _zone_filename(self) -> str:
        """Returns filename of zone file, relative to repository root."""
        filename = self._get_provider_option("git_path")
        if filename is None:
            filename = ""
        if "{domain}" in filename:
            filename = filename.replace("{domain}", self.domain)
        else:
            filename = os.path.join(filename, self.domain)
        # This collapses any ./ or ../ path components:
        return os.path.relpath(os.path.join("/", filename), "/")

    def _authenticate(self):
        url = self._get_provider_option("git_repo")

        if self.temp_dir is None:
            self.temp_dir = TemporaryDirectory(prefix="dns-lexicon-git-")
            self.filename = os.path.join(self.temp_dir.name, self._zone_filename())

        if self.repo is None:
            kwargs = {}
            branch = self._get_provider_option("git_branch")
            if branch is not None:
                kwargs["branch"] = branch

            try:
                self.repo = _clone(url, self.temp_dir.name, **kwargs)
            except git.exc.GitCommandError as e:
                LOGGER.error(f"Could not clone {url}: {e.stderr}")
                raise AuthenticationError
            else:
                LOGGER.info(f"Cloned {url}")

        try:
            f = open(self.filename, "rt")
        except IOError:
            LOGGER.error(f"{self.filename} not present in {url}")
            raise AuthenticationError
        else:
            f.close()

        # Tests assume this is non-None on success:
        self.domain_id = self.domain

    def _commit(self) -> bool:
        self.repo.index.add('*')

        if self.repo.head.is_valid() and not self.repo.index.diff(self.repo.head.commit):
            LOGGER.info("Nothing to commit!")
            return True

        author = git.Actor(self._get_provider_option("git_name"), self._get_provider_option("git_email"))

        message = self._get_provider_option("git_message")
        if message is None:
            message = "Update {domain} (automated commit)"
        if "{domain}" in message:
            message = message.replace("{domain}", self.domain)

        commit = self.repo.index.commit(message, author=author, committer=author)
        LOGGER.info(f"Committed {commit.hexsha}")

        kwargs = {}
        branch = self._get_provider_option("git_push_branch")
        if branch is not None:
            kwargs["branch"] = branch

        return _push(self.repo, **kwargs)

    def _create_record(self, rtype, name, content):
        result = super(Provider, self)._create_record(rtype, name, content)
        if result:
            result = self._commit()
        return result

    def _update_record(self, identifier, rtype, name, content):
        result = super(Provider, self)._update_record(identifier, rtype, name, content)
        if result:
            result = self._commit()
        return result

    def _delete_record(self, identifier, rtype, name, content):
        result = super(Provider, self)._delete_record(identifier, rtype, name, content)
        if result:
            result = self._commit()
        return result
