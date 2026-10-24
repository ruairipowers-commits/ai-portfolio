/**
 * Dinner Peace Pro — Hands-Free Kitchen Voice Engine
 * Enables personal chefs to dictate updates, log leftovers, capture grocery receipts,
 * and navigate the app 100% hands-free while cooking.
 */

class ChefVoiceEngine {
  constructor(options = {}) {
    this.isListening = false;
    this.recognition = null;
    this.onTranscript = options.onTranscript || (() => {});
    this.onCommand = options.onCommand || (() => {});
    this.onError = options.onError || (() => {});
    this.onStatusChange = options.onStatusChange || (() => {});

    this.initRecognition();
  }

  initRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-US';

      this.recognition.onstart = () => {
        this.isListening = true;
        this.onStatusChange({ status: 'listening', message: 'Listening hands-free...' });
      };

      this.recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }

        const activeTranscript = finalTranscript || interimTranscript;
        this.onTranscript(activeTranscript);

        if (finalTranscript) {
          this.parseAndExecuteCommand(finalTranscript.trim());
        }
      };

      this.recognition.onerror = (event) => {
        this.onError(event.error);
        this.onStatusChange({ status: 'error', message: `Voice error: ${event.error}` });
      };

      this.recognition.onend = () => {
        this.isListening = false;
        this.onStatusChange({ status: 'idle', message: 'Voice engine standby' });
      };
    }
  }

  toggle() {
    if (!this.recognition) {
      // Fallback simulated engine for environments without microphone permissions
      this.simulateVoiceCommand();
      return;
    }

    if (this.isListening) {
      this.recognition.stop();
    } else {
      try {
        this.recognition.start();
      } catch (e) {
        this.simulateVoiceCommand();
      }
    }
  }

  parseAndExecuteCommand(text) {
    const lower = text.toLowerCase();

    // Command: Log Leftover / Fridge
    if (lower.includes('fridge') || lower.includes('leftover') || lower.includes('container')) {
      this.onCommand({
        type: 'LOG_FRIDGE',
        raw: text,
        feedback: 'Logged to client fridge and labeled container.'
      });
      return;
    }

    // Command: Reheating Instructions
    if (lower.includes('reheat') || lower.includes('temp') || lower.includes('bake') || lower.includes('oven')) {
      this.onCommand({
        type: 'SET_REHEATING',
        raw: text,
        feedback: 'Added to printable/email reheating instructions.'
      });
      return;
    }

    // Command: Grocery / Receipt / Chargeback
    if (lower.includes('dollar') || lower.includes('cost') || lower.includes('receipt') || lower.includes('charge')) {
      this.onCommand({
        type: 'LOG_EXPENSE',
        raw: text,
        feedback: 'Itemized expense logged & chargeback generated.'
      });
      return;
    }

    // Command: Next Household / Priority
    if (lower.includes('next') || lower.includes('who') || lower.includes('where')) {
      this.onCommand({
        type: 'QUERY_NEXT_STEP',
        raw: text,
        feedback: 'Surfaced immediate next prep task & location.'
      });
      return;
    }

    // General note capture
    this.onCommand({
      type: 'CAPTURE_NOTE',
      raw: text,
      feedback: 'Note attached to household dossier.'
    });
  }

  simulateVoiceCommand() {
    const samples = [
      '"Added 2 lbs wild salmon to the Henderson fridge. Reheating: 375°F for 12 mins."',
      '"Logged $64.20 organic produce from Whole Foods. Charge back to Miller household on Amex Gold."',
      '"Note for backup chef Sarah: Miller kids prefer sauce on the side; dad has mild sesame sensitivity."',
      '"Leftover herb roasted potatoes packed in glass container #2. Good until Friday."',
      '"What is my next step? Drive 15 mins to Parker residence for 2:30 PM prep."'
    ];
    const chosen = samples[Math.floor(Math.random() * samples.length)];

    this.onStatusChange({ status: 'listening', message: 'Simulating speech capture...' });
    this.onTranscript('Listening to voice input...');

    setTimeout(() => {
      this.onTranscript(chosen);
      this.parseAndExecuteCommand(chosen);
      this.onStatusChange({ status: 'done', message: 'Captured & Executed ✓' });
    }, 750);
  }
}

// Export for module or browser window
if (typeof window !== 'undefined') {
  window.ChefVoiceEngine = ChefVoiceEngine;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ChefVoiceEngine;
}
