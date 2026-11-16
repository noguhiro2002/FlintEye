import { chromium as chromiumType, firefox, webkit } from 'playwright';
const selected = process.env.FLINTEYE_BROWSER || 'chromium';
if (!['chromium', 'firefox', 'webkit'].includes(selected)) throw new Error('Unknown browser engine');
const type = {chromium: chromiumType, firefox, webkit}[selected];
export const chromium = {
  launch(options = {}) {
    if (selected !== 'chromium') { const {args, executablePath, ...rest} = options; return type.launch({...rest, ...(selected === 'webkit' && process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH} : {})}); }
    return type.launch(options);
  }
};
