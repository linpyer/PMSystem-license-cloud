import { vi } from 'vitest'

class ResizeObserverMock { observe(){} unobserve(){} disconnect(){} }
vi.stubGlobal('ResizeObserver', ResizeObserverMock)
vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
  matches: false, media: query, onchange: null,
  addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
})))
Object.defineProperty(globalThis, 'crypto', { value: { randomUUID: () => '00000000-0000-4000-8000-000000000001' } })
