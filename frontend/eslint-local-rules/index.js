/**
 * Local ESLint plugin: no-ampersand-style
 *
 * 禁止在 React 内联 `style={{...}}` 中使用 `&:` 形式的键。
 * `&:` 是 SCSS / CSS-in-JS 库（Emotion、styled-components）的父选择器语法，
 * 不会被 React 原生 style 属性支持，会在运行时产生：
 *   "Unsupported style property \"&:first-child\""
 * 这类难以诊断的 console 错误。
 *
 * 遇到该写法时应改为：
 *   - 真正的 CSS 类（写进 .css 文件用 :first-child 等选择器）
 *   - 或迁移到 CSS-in-JS 库
 */
const noAmpersandStyle = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Disallow SCSS `&:` parent-selector syntax inside React inline style props',
    },
    messages: {
      invalid:
        '`{{key}}` 是 SCSS / CSS-in-JS 父选择器语法，' +
        '不能用在 React 原生内联 style 属性上（运行时 React 会报 "Unsupported style property"）。' +
        '改用 CSS 类（在 .css 中用 :first-child 等真实选择器），' +
        '或迁移到 Emotion / styled-components 等 CSS-in-JS 库。',
    },
    schema: [],
  },
  create(context) {
    return {
      // 匹配 <tag style={{ ... }} />
      'JSXAttribute[name.name="style"] ObjectExpression'(node) {
        for (const prop of node.properties) {
          // 只看字面量键（computed 跳过、字符串/数字字面量暂时不处理）
          if (prop.type !== 'Property' || prop.computed) continue
          const keyName =
            prop.key.type === 'Identifier'
              ? prop.key.name
              : prop.key.type === 'Literal' && typeof prop.key.value === 'string'
                ? prop.key.value
                : null
          if (keyName && /^&:/.test(keyName)) {
            context.report({
              node: prop,
              messageId: 'invalid',
              data: { key: keyName },
            })
          }
        }
      },
    }
  },
}

const plugin = {
  meta: { name: 'eslint-plugin-local', version: '0.0.0' },
  rules: {
    'no-ampersand-style': noAmpersandStyle,
  },
}

export default plugin
