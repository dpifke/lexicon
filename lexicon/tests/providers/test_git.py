"""Integration tests for Git provider"""
import os.path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

import dns
import git
import pytest

from lexicon.providers.git import _push as unpatched_push
from lexicon.tests.providers import integration_tests, test_localzone


@pytest.fixture
def upstream_repo_path() -> str:
    with TemporaryDirectory(prefix="dns-lexicon-git-test-upstream-") as upstream_path:
        # Initialize a bare repository
        upstream_repo = git.Repo.init(upstream_path, bare=True)

        # Clone it, add testdata, commit, and push
        with TemporaryDirectory(prefix="dns-lexicon-git-test-") as clone_path:
            repo = git.Repo.clone_from(upstream_path, clone_path)
            with open(os.path.join(clone_path, "example.com"), "wt") as zonefile:
                zonefile.write(test_localzone.ZONEFILE)
            repo.index.add("example.com")
            author = git.Actor("John Doe", "john@example.com")
            repo.index.commit("New domain", author=author, committer=author)
            unpatched_push(repo)

        yield upstream_path


@pytest.fixture(autouse=True)
def _mock_clone(upstream_repo_path):
    def _clone(from_url: str, to_path: str, **kwargs) -> git.Repo:
        return git.Repo.clone_from(upstream_repo_path, to_path, **kwargs)

    def _push(repo: git.Repo, **kwargs) -> bool:
        result = unpatched_push(repo, **kwargs)
        # TODO: re-check out, to verify changes took
        return result

    with mock.patch("lexicon.providers.git._clone", new=_clone):
        with mock.patch("lexicon.providers.git._push", new=_push):
            yield


class GitTests(TestCase, integration_tests.IntegrationTestsV2):
    """TestCase for Git provider"""

    provider_name = "git"
    domain = "example.com"

    def _test_fallback_fn(self):
        def fallback(name):
            if name in ("git_path", "git_branch", "git_push_branch"):
                return None
            return super(GitTests, self)._test_fallback_fn()(name)
        return fallback

    def test_zone_filename(self):
        for path, expect in (
            # Simplest usage is just a directory name, relative to repo root:
            ("", "example.com"),
            ("foo", "foo/example.com"),

            # Can also substitute {domain} for one or :
            ("{domain}", "example.com"),
            ("db.{domain}", "db.example.com"),
            ("{domain}.zone", "example.com.zone"),
            ("foo/db.{domain}.zone", "foo/db.example.com.zone"),
            ("{domain}/db.{domain}.zone", "example.com/db.example.com.zone"),

            # Relative paths should be normalized and kept within repository:
            ("/foo", "foo/example.com"),
            ("./foo", "foo/example.com"),
            ("foo/../bar", "bar/example.com"),
            ("../../../foo", "foo/example.com"),
            ("foo/../..", "example.com"),
        ):
            config = self._test_config()
            config.add_config_source(
                integration_tests.EngineOverrideConfigSource({
                    "git_path": path,
                }), 0
            )
            actual = self.provider_module.Provider(config)._zone_filename()
            self.assertEqual(actual, expect, msg=f"git_path is {path!r}")
