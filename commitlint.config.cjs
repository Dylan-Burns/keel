// Conventional Commits, checked on every PR commit in CI and locally by the
// conventional-pre-commit hook. Scopes are the module names of the
// repository.
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'docs', 'test', 'refactor', 'perf', 'build', 'ci', 'chore', 'revert'],
    ],
    'scope-enum': [
      2,
      'always',
      [
        'parser', 'sections', 'chunker', 'index', 'understanding', 'retriever',
        'prompt', 'provider', 'citations', 'api', 'web', 'eval', 'edgar',
        'export', 'infra', 'docs', 'deps', 'release', 'main', 'cli', 'cache', 'hooks',
      ],
    ],
    'header-max-length': [2, 'always', 72],
    'body-max-line-length': [2, 'always', 100],
    'subject-case': [2, 'never', ['sentence-case', 'start-case', 'pascal-case', 'upper-case']],
  },
};
