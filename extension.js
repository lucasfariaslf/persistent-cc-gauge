'use strict';

const fs = require('fs');
const path = require('path');
const vscode = require('vscode');
const { planPatch, planRevert } = require('./src/patch');

// VS Code resolves extension ids case-insensitively, but try both spellings.
const CLAUDE_EXTENSION_IDS = ['Anthropic.claude-code', 'anthropic.claude-code'];
const BUNDLE_REL_PATH = path.join('webview', 'index.js');
const BACKUP_SUFFIX = '.pcg.bak';

function resolveBundlePath() {
  for (const id of CLAUDE_EXTENSION_IDS) {
    const ext = vscode.extensions.getExtension(id);
    if (!ext) continue;
    const bundle = path.join(ext.extensionPath, BUNDLE_REL_PATH);
    if (fs.existsSync(bundle)) return bundle;
  }
  return undefined;
}

function isEnabled() {
  return vscode.workspace.getConfiguration('persistentCcGauge').get('enabled', true);
}

function promptReload(message) {
  vscode.window.showInformationMessage(message, 'Reload Window').then((choice) => {
    if (choice === 'Reload Window') {
      vscode.commands.executeCommand('workbench.action.reloadWindow');
    }
  });
}

// Atomic write: temp file in the same directory, then rename over the target.
// The temp name carries pid + randomness so two VS Code windows patching the
// same bundle at startup cannot collide on the temp file. rename(2) within a
// directory is atomic, so the bundle is never left half-written; concurrent
// writers just resolve to last-writer-wins of identical idempotent content.
function writeAtomic(target, content) {
  const unique = `${process.pid}-${Math.random().toString(36).slice(2)}`;
  const tmp = path.join(path.dirname(target), `.pcg-${unique}-${path.basename(target)}.tmp`);
  try {
    fs.writeFileSync(tmp, content, 'utf8');
    fs.renameSync(tmp, target);
  } catch (err) {
    try { fs.rmSync(tmp, { force: true }); } catch { /* best effort */ }
    throw err;
  }
}

// Save the pristine bundle once as a safety net, written from the in-memory copy
// we just read (not re-read from disk, which could race with another window
// patching it). Only when that copy is actually pristine, so .pcg.bak is never a
// patched bundle. Revert does not depend on this (it reconstructs the original
// from data embedded in each marker), so it is best-effort.
function backupOnce(target, pristineSource) {
  const backup = target + BACKUP_SUFFIX;
  if (fs.existsSync(backup)) return;
  if (pristineSource.includes('/*gauge-always')) return; // not pristine; skip
  try {
    fs.writeFileSync(backup, pristineSource, 'utf8');
  } catch {
    // best effort
  }
}

function apply(interactive) {
  const bundle = resolveBundlePath();
  if (!bundle) {
    if (interactive) vscode.window.showWarningMessage('persistent-cc-gauge: Claude Code extension not found.');
    return;
  }
  let source;
  try {
    source = fs.readFileSync(bundle, 'utf8');
  } catch (err) {
    if (interactive) vscode.window.showErrorMessage(`persistent-cc-gauge: cannot read the Claude bundle (${err.message}).`);
    return;
  }

  const plan = planPatch(source);

  if (plan.status === 'patched') {
    try {
      backupOnce(bundle, source);  // save the pristine bundle before writing
      writeAtomic(bundle, plan.content);
    } catch (err) {
      vscode.window.showErrorMessage(`persistent-cc-gauge: write failed (${err.message}). Check permissions on the Claude Code extension.`);
      return;
    }
    const skipped = plan.skipped.length ? ` (skipped: ${plan.skipped.join(', ')})` : '';
    promptReload(`persistent-cc-gauge: gauge patch applied${skipped}. Reload to affect open Claude panels.`);
    return;
  }

  if (!interactive) return; // silent on startup for no-op / non-applied states

  switch (plan.status) {
    case 'already':
      vscode.window.showInformationMessage(
        plan.skipped.length
          ? `persistent-cc-gauge: applied; could not match: ${plan.skipped.join(', ')} (this Claude version may have changed).`
          : 'persistent-cc-gauge: already applied, nothing to do.');
      break;
    case 'not-found':
      vscode.window.showWarningMessage('persistent-cc-gauge: the gauge code was not found in this Claude Code version; nothing was modified.');
      break;
    case 'ambiguous':
      vscode.window.showWarningMessage('persistent-cc-gauge: found more than one matching site; refused to guess and left the bundle untouched.');
      break;
    default:
      vscode.window.showWarningMessage(`persistent-cc-gauge: did not patch (${plan.message}); left the bundle untouched.`);
      break;
  }
}

function revert(interactive) {
  const bundle = resolveBundlePath();
  if (!bundle) {
    if (interactive) vscode.window.showWarningMessage('persistent-cc-gauge: Claude Code extension not found.');
    return;
  }
  let source;
  try {
    source = fs.readFileSync(bundle, 'utf8');
  } catch (err) {
    if (interactive) vscode.window.showErrorMessage(`persistent-cc-gauge: cannot read the Claude bundle (${err.message}).`);
    return;
  }

  const plan = planRevert(source);

  if (plan.status === 'reverted') {
    try {
      writeAtomic(bundle, plan.content);
    } catch (err) {
      vscode.window.showErrorMessage(`persistent-cc-gauge: write failed (${err.message}).`);
      return;
    }
    promptReload('persistent-cc-gauge: reverted to the stock gauge. Reload to apply.');
    return;
  }

  if (!interactive) return;

  if (plan.status === 'not-patched') {
    vscode.window.showInformationMessage('persistent-cc-gauge: not patched, nothing to revert.');
  } else {
    vscode.window.showWarningMessage(`persistent-cc-gauge: could not revert (${plan.message}). If the bundle is in an unexpected state, reinstall the Claude Code extension.`);
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand('persistentCcGauge.apply', () => apply(true)),
    vscode.commands.registerCommand('persistentCcGauge.revert', () => revert(true)),
  );

  // Re-apply on every startup so the patch survives Claude Code auto-updates
  // (each update ships a fresh, unpatched bundle). No-op once already patched.
  if (isEnabled()) {
    try {
      apply(false);
    } catch (err) {
      console.error('[persistent-cc-gauge]', err);
    }
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
