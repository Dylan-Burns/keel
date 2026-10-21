// Conventional Commits, checked on every PR commit in CI and locally by the
// conventional-pre-commit hook. Scopes are the module names from chapter 17.
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
        'stage-00', 'stage-01', 'stage-02', 'stage-03', 'stage-04', 'stage-05',
        'stage-06', 'stage-07', 'stage-08', 'stage-09', 'stage-10', 'stage-11',
        'stage-12', 'stage-13', 'stage-14', 'stage-15', 'stage-16', 'stage-17',
        'stage-18', 'stage-19', 'stage-20', 'stage-21', 'stage-22',
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
