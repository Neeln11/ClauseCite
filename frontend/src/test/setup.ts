import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library only registers its own afterEach hook when the test framework
// exposes globals. This project imports `describe`/`it`/`expect` explicitly, so
// cleanup has to be wired up by hand — without it, every render accumulates in
// document.body and the second `getByRole` in a file starts finding duplicates.
afterEach(cleanup)
