'use strict';

// Copies the runtime files into ~/.vscode/extensions/persistent-cc-gauge so
// VS Code loads it as an unpacked extension. Re-run after changing the source,
// then reload the window. No build step, no packaging.

const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.join(__dirname, '..');
const DEST = path.join(os.homedir(), '.vscode', 'extensions', 'persistent-cc-gauge');
const INCLUDE = ['package.json', 'extension.js', 'src', 'README.md', 'LICENSE', 'CHANGELOG.md'];

function copyInto(from, to) {
  const stat = fs.statSync(from);
  if (stat.isDirectory()) {
    fs.mkdirSync(to, { recursive: true });
    for (const entry of fs.readdirSync(from)) {
      copyInto(path.join(from, entry), path.join(to, entry));
    }
  } else {
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(from, to);
  }
}

fs.rmSync(DEST, { recursive: true, force: true });
for (const item of INCLUDE) {
  const from = path.join(ROOT, item);
  if (fs.existsSync(from)) copyInto(from, path.join(DEST, item));
}

console.log('Installed to ' + DEST);
console.log('Run "Developer: Reload Window" in VS Code to activate.');
