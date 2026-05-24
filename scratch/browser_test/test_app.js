const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

(async () => {
  console.log("=== STARTING AUTOMATED BROWSER VERIFICATION ===");
  
  // Resolve system Chrome path
  const chromePaths = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.USERPROFILE, "AppData\\Local\\Google\\Chrome\\Application\\chrome.exe")
  ];
  
  let executablePath = "";
  for (const p of chromePaths) {
    if (fs.existsSync(p)) {
      executablePath = p;
      break;
    }
  }
  
  if (!executablePath) {
    console.error("CRITICAL: Google Chrome executable not found on standard paths!");
    process.exit(1);
  }
  
  console.log(`Using Chrome binary at: ${executablePath}`);
  
  const browser = await puppeteer.launch({
    executablePath: executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  
  // Capture console logs
  const consoleLogs = [];
  page.on('console', msg => {
    const text = msg.text();
    consoleLogs.push(`[Console ${msg.type().toUpperCase()}] ${text}`);
    console.log(`[Browser Console] ${text}`);
  });
  
  page.on('pageerror', err => {
    consoleLogs.push(`[Uncaught Page Error] ${err.toString()}`);
    console.error(`[Browser Uncaught Error] ${err}`);
  });
  
  try {
    console.log("Navigating to http://127.0.0.1:8000/...");
    await page.goto("http://127.0.0.1:8000/", { waitUntil: 'networkidle2', timeout: 15000 });
    
    // Verify basic DOM elements
    console.log("Checking landing page elements...");
    const hasLogo = await page.$('.wordmark-name') !== null;
    const hasSuggestions = await page.$('.suggestions') !== null;
    console.log(`- Logo element present? ${hasLogo}`);
    console.log(`- Suggestion questions visible? ${hasSuggestions}`);
    
    // Focus and input the SGLT2 sickle cell query
    console.log("Typing sickle cell / SGLT2 query into textarea...");
    await page.focus('#ta');
    const query = "What are the potential long-term effects of SGLT2 inhibitors on kidney function and intraglomerular pressure in patients with sickle cell disease?";
    await page.keyboard.type(query);
    
    // Let the textarea autoResize trigger
    await page.evaluate(() => {
      const ta = document.getElementById('ta');
      const event = new Event('input', { bubbles: true });
      ta.dispatchEvent(event);
    });
    
    // Verify send button is active
    const isSendActive = await page.evaluate(() => {
      return document.getElementById('send-btn').classList.contains('active');
    });
    console.log(`- Send button activated? ${isSendActive}`);
    
    // Click send
    console.log("Clicking send button to dispatch RAG pipeline...");
    await page.click('#send-btn');
    
    // Wait for the papers card and answer card to be generated
    console.log("Waiting 15 seconds for PubMed fallback search, embeddings, and Groq generation...");
    await new Promise(r => setTimeout(r, 15000));
    
    // Verify RAG visual results
    console.log("Verifying RAG pipeline rendering...");
    const hasStreamCard = await page.$('.stream-card') !== null;
    const hasAnswerCard = await page.$('.answer-card') !== null;
    const hasWarningBanner = await page.$('.warning-banner') !== null;
    const hasNhisWidget = await page.$('.nhis-widget') !== null;
    
    console.log(`- Stream card (PubMed retrieved papers) present? ${hasStreamCard}`);
    console.log(`- Answer card present? ${hasAnswerCard}`);
    console.log(`- Cohort Mismatch Alert Box parsed & rendered? ${hasWarningBanner}`);
    console.log(`- Ghana NHIS Medication pill grid rendered? ${hasNhisWidget}`);
    
    if (hasWarningBanner) {
      const warningText = await page.evaluate(() => {
        return document.querySelector('.warning-banner-text').innerText;
      });
      console.log(`Warning Banner Text:\n"${warningText}"`);
    }
    
    if (hasNhisWidget) {
      const meds = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('.nhis-med-row')).map(row => {
          return {
            name: row.querySelector('.nhis-med-name').innerText,
            status: row.querySelector('.nhis-med-status').innerText,
            avail: row.querySelector('.nhis-med-avail').innerText
          };
        });
      });
      console.log("NHIS Coded Medications:");
      console.log(JSON.stringify(meds, null, 2));
    }
    
    // Take a screenshot of the completed UI
    const screenshotPath = "C:\\Users\\HomePC\\.gemini\\antigravity-ide\\brain\\4f721d03-ea72-4086-969d-cba59b1e448f\\screenshot.png";
    console.log(`Taking full screenshot of the UI and saving to: ${screenshotPath}`);
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log("Screenshot successfully saved!");
    
    console.log("=== BROWSER VERIFICATION COMPLETED SUCCESSFULLY ===");
  } catch (err) {
    console.error("ERROR during browser verification:", err);
  } finally {
    await browser.close();
  }
})();
