// @tested-functions linkifyUiLinks, documentUrl, reviewQueueUrl, reviewItemUrl
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  documentUrl,
  linkifyUiLinks,
  reviewItemUrl,
  reviewQueueUrl,
} from './uiLinks.js'

const DOC_ID = 'a'.repeat(64)

test('workbench markers become frontend links and malformed markers stay literal', () => {
  const previous = process.env.MBFORGE_FRONTEND_URL
  process.env.MBFORGE_FRONTEND_URL = 'http://ui.test/'
  try {
    assert.equal(reviewQueueUrl(), 'http://ui.test/review')
    assert.equal(
      reviewItemUrl('designation_unbound', 'abc123'),
      'http://ui.test/review?kind=designation_unbound&id=abc123',
    )
    assert.equal(
      documentUrl(DOC_ID, 7),
      `http://ui.test/open?doc=${DOC_ID}&page=7`,
    )

    const rendered = linkifyUiLinks(
      [
        '复核 [[ui:review]]',
        '该项 [[ui:review:low_conf_molecule:mol-1]]',
        `文档 [[ui:doc:${DOC_ID}]]`,
        `页 [[ui:doc:${DOC_ID}:12]]`,
        '队列 [[ui:queue]]',
        '[[ui:unknown]]',
        '[[ui:review:not_a_kind:mol-1]]',
        '[[ui:review:low_conf_molecule:]]',
        `[[ui:doc:${DOC_ID}:0]]`,
      ].join('\n'),
    )

    assert.ok(rendered.includes('[复核中心](http://ui.test/review)'), rendered)
    assert.ok(
      rendered.includes(
        '[复核项](http://ui.test/review?kind=low_conf_molecule&id=mol-1)',
      ),
      rendered,
    )
    assert.ok(
      rendered.includes(`[文档](http://ui.test/open?doc=${DOC_ID})`),
      rendered,
    )
    assert.ok(
      rendered.includes(
        `[文档·p.12](http://ui.test/open?doc=${DOC_ID}&page=12)`,
      ),
      rendered,
    )
    assert.ok(rendered.includes('[处理队列](http://ui.test/queue)'), rendered)

    // An unknown surface, an unknown review kind, a missing item id and page 0
    // each stay literal instead of linking a route that would land elsewhere.
    for (const marker of [
      '[[ui:unknown]]',
      '[[ui:review:not_a_kind:mol-1]]',
      '[[ui:review:low_conf_molecule:]]',
      `[[ui:doc:${DOC_ID}:0]]`,
    ]) {
      assert.ok(rendered.includes(marker), marker)
    }
  } finally {
    if (previous === undefined) delete process.env.MBFORGE_FRONTEND_URL
    else process.env.MBFORGE_FRONTEND_URL = previous
  }
})
