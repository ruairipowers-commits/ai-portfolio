---
icon: material/lightbulb-on-outline
title: Suggest a project
---

# Projects

<nav class="subtabs" markdown>
[Industry projects](index.md)
[Personal projects](../personal/index.md)
[Suggest a project](suggestions.md){ .active }
</nav>

What should I build next? Suggest a problem, a project or a technology you'd like to see me take on, and upvote the
ideas others have shared. Every day I get the top ten by votes, with the new ones marked. I can start any of them
in Claude with the same [project framework](../about.md#how-i-built-this-site-with-ai) that built the rest of this
site.

New suggestions appear below once I've reviewed them. Your name and contact are optional and never shown on the
site; leave them only if you'd like a reply.

<form class="suggest" data-suggest>
  <label for="sg-idea">Your idea</label>
  <textarea id="sg-idea" name="idea" rows="4" minlength="10" maxlength="1500" required
    placeholder="e.g. An agent that reconciles corporate actions across custodians"></textarea>
  <div class="suggest__row">
    <div><label for="sg-name">Name (optional)</label><input id="sg-name" name="name" maxlength="80"></div>
    <div><label for="sg-contact">Email or LinkedIn (optional)</label><input id="sg-contact" name="contact" maxlength="120"></div>
  </div>
  <input class="suggest__hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
  <button type="submit" class="md-button md-button--primary">Send suggestion</button>
  <p class="suggest__status" data-status role="status"></p>
</form>

## Ideas so far

<div class="ideas" data-suggestions><p class="ideas__empty">Loading suggestions…</p></div>
