import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import local from './eslint-local-rules/index.js'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parserOptions: {
        project: './tsconfig.json',
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      local,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // Relax void-return for React event handlers (onClick, onChange, etc.)
      '@typescript-eslint/no-confusing-void-expression': 'off',
      // Allow promises in event handlers (async onClick etc.)
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: false },
      ],
      // The __TAURI__ and __TAURI_INTERNALS__ globals need any — keep
      // the rest of the codebase strict by promoting this to error.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'warn',
      '@typescript-eslint/no-unsafe-return': 'warn',
      '@typescript-eslint/no-unsafe-assignment': 'warn',
      // Template expressions with non-string values
      '@typescript-eslint/restrict-template-expressions': 'off',
      // Unused vars: allow _ prefix
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // Data-fetching in useEffect is intentional
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/set-state-in-effect': 'off',

      // Local rules
      // 禁止 React 内联 style 中使用 SCSS 父选择器 `&:xxx` 语法
      'local/no-ampersand-style': 'error',
    },
  },
  {
    files: ['src/components/icons/index.tsx', 'src/components/ui/Toast.tsx', 'src/context/AppContext.tsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
  {
    files: ['**/*.test.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
    },
  },
)
