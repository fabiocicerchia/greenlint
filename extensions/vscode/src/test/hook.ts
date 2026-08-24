// Point `require('vscode')` at the shim, for `node --test --require`.
//
// A loader hook rather than a build-time alias so the modules under test are
// the ones that ship, compiled the same way, importing the same specifier.
import Module from 'module';

import { vscode } from './vscode-shim';

const load = (Module as unknown as { _load: (...args: unknown[]) => unknown })._load;
(Module as unknown as { _load: (...args: unknown[]) => unknown })._load = function (
  request: unknown,
  ...rest: unknown[]
) {
  return request === 'vscode' ? vscode : load.call(this, request, ...rest);
};
