// Google TypeScript Style Guide, enforced with gts (the Google TypeScript
// Style package: ESLint flat config plus Prettier), with the React hooks and
// jsx-a11y plugins and the rules of the guide that gts leaves to review.
import gts from 'gts';
import jsdoc from 'eslint-plugin-jsdoc';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'playwright-report/**',
      'test-results/**',
    ],
  },
  ...gts,
  {
    // This config file is an ES module (package.json sets type: module).
    files: ['*.js'],
    languageOptions: {sourceType: 'module'},
  },
  jsxA11y.flatConfigs.recommended,
  reactHooks.configs.flat['recommended-latest'],
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parserOptions: {
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {jsdoc},
    rules: {
      // Google TypeScript Style Guide
      curly: ['error', 'all'],
      eqeqeq: ['error', 'always'],
      'no-var': 'error',
      'prefer-const': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        {prefer: 'type-imports', fixStyle: 'separate-type-imports'},
      ],
      '@typescript-eslint/consistent-type-definitions': ['error', 'interface'],
      '@typescript-eslint/array-type': ['error', {default: 'array'}],
      '@typescript-eslint/explicit-module-boundary-types': 'error',
      '@typescript-eslint/naming-convention': [
        'error',
        {selector: 'default', format: ['camelCase']},
        {
          selector: 'variable',
          format: ['camelCase', 'PascalCase', 'UPPER_CASE'],
        },
        {selector: 'function', format: ['camelCase', 'PascalCase']},
        {selector: 'typeLike', format: ['PascalCase']},
        {selector: 'enumMember', format: ['UPPER_CASE']},
        {selector: 'import', format: ['camelCase', 'PascalCase']},
        {selector: 'objectLiteralProperty', format: null},
        {
          selector: 'parameter',
          format: ['camelCase'],
          leadingUnderscore: 'allow',
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'TSModuleDeclaration',
          message: 'Google TS style: no namespaces; use modules.',
        },
        {
          selector: 'TSEnumDeclaration[const=true]',
          message: 'Google TS style: no const enums.',
        },
      ],
      'jsdoc/require-jsdoc': [
        'error',
        {
          publicOnly: true,
          require: {
            FunctionDeclaration: true,
            ClassDeclaration: true,
            ArrowFunctionExpression: true,
            FunctionExpression: true,
          },
          contexts: ['TSInterfaceDeclaration', 'TSTypeAliasDeclaration'],
        },
      ],
      'jsdoc/require-param-type': 'off',
      'jsdoc/require-returns-type': 'off',
    },
  },
  {
    // Application code: named exports only (Google TS style). Tool config
    // files below need default exports and are exempt.
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'ExportDefaultDeclaration',
          message: 'Google TS style: use named exports.',
        },
        {
          selector: 'TSModuleDeclaration',
          message: 'Google TS style: no namespaces; use modules.',
        },
      ],
    },
  },
  {
    files: ['src/**/*.test.{ts,tsx}', 'e2e/**/*.ts', '*.config.ts'],
    rules: {
      'jsdoc/require-jsdoc': 'off',
    },
  },
);
