// Dinner Peace & Dinner Peace Pro Portal Interactive Application Scripts

document.addEventListener('DOMContentLoaded', () => {
  // 1. Mobile Menu Toggle
  const mobileToggle = document.querySelector('.mobile-toggle');
  const navLinks = document.querySelector('.nav-links');

  if (mobileToggle && navLinks) {
    mobileToggle.addEventListener('click', () => {
      const isVisible = navLinks.style.display === 'flex';
      navLinks.style.display = isVisible ? 'none' : 'flex';
      if (!isVisible) {
        navLinks.style.flexDirection = 'column';
        navLinks.style.position = 'absolute';
        navLinks.style.top = '80px';
        navLinks.style.left = '0';
        navLinks.style.right = '0';
        navLinks.style.background = 'rgba(248, 246, 241, 0.98)';
        navLinks.style.padding = '24px';
        navLinks.style.borderBottom = '1px solid #E5DFD6';
      }
    });
  }

  // 2. Billing Toggle (Monthly / Annual)
  const billingCheckbox = document.getElementById('billing-toggle');
  const monthlyLabel = document.getElementById('label-monthly');
  const annualLabel = document.getElementById('label-annual');
  const priceDisplay = document.getElementById('pro-price-val');
  const cycleDisplay = document.getElementById('pro-cycle-val');
  const pricingNote = document.getElementById('pricing-note-text');

  // Chef Pro Portal pricing displays
  const chefPrice1 = document.getElementById('chef-price-1');
  const chefCycle1 = document.getElementById('chef-cycle-1');
  const chefPrice2 = document.getElementById('chef-price-2');
  const chefCycle2 = document.getElementById('chef-cycle-2');

  if (billingCheckbox) {
    billingCheckbox.addEventListener('change', () => {
      const isAnnual = billingCheckbox.checked;
      if (isAnnual) {
        monthlyLabel?.classList.remove('active');
        annualLabel?.classList.add('active');
        if (priceDisplay) priceDisplay.textContent = '$39';
        if (cycleDisplay) cycleDisplay.textContent = '/ year ($3.25/mo)';
        if (pricingNote) pricingNote.textContent = 'Billed annually at $39/yr. Save 35% compared to monthly.';

        if (chefPrice1) chefPrice1.textContent = '$24';
        if (chefCycle1) chefCycle1.textContent = '/ month (billed $290/yr)';
        if (chefPrice2) chefPrice2.textContent = '$49';
        if (chefCycle2) chefCycle2.textContent = '/ month (billed $590/yr)';
      } else {
        annualLabel?.classList.remove('active');
        monthlyLabel?.classList.add('active');
        if (priceDisplay) priceDisplay.textContent = '$4.99';
        if (cycleDisplay) cycleDisplay.textContent = '/ month';
        if (pricingNote) pricingNote.textContent = 'Billed monthly. Cancel anytime with one tap in your settings.';

        if (chefPrice1) chefPrice1.textContent = '$29';
        if (chefCycle1) chefCycle1.textContent = '/ month';
        if (chefPrice2) chefPrice2.textContent = '$59';
        if (chefCycle2) chefCycle2.textContent = '/ month';
      }
    });
  }

  // 3. Pricing Audience Toggle (Families vs Personal Chefs)
  const audienceFamilyBtn = document.getElementById('audience-family-btn');
  const audienceChefBtn = document.getElementById('audience-chef-btn');
  const pricingGridFamily = document.getElementById('pricing-grid-family');
  const pricingGridChef = document.getElementById('pricing-grid-chef');

  if (audienceFamilyBtn && audienceChefBtn) {
    audienceFamilyBtn.addEventListener('click', () => {
      audienceFamilyBtn.classList.add('active');
      audienceChefBtn.classList.remove('active');
      if (pricingGridFamily) pricingGridFamily.style.display = 'grid';
      if (pricingGridChef) pricingGridChef.style.display = 'none';
    });

    audienceChefBtn.addEventListener('click', () => {
      audienceChefBtn.classList.add('active');
      audienceFamilyBtn.classList.remove('active');
      if (pricingGridFamily) pricingGridFamily.style.display = 'none';
      if (pricingGridChef) pricingGridChef.style.display = 'grid';
    });
  }

  // 4. Pro Portal 5-Module Navigation (PRO_SPEC.md)
  const portalNavTabs = document.querySelectorAll('.portal-nav-tab');
  const portalPanes = document.querySelectorAll('.portal-content-pane');

  portalNavTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      portalNavTabs.forEach(t => t.classList.remove('active'));
      portalPanes.forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-portal-target');
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add('active');
      }
    });
  });

  // 5. Voice-Driven Field Logger Simulation (PRO_SPEC.md Module 4)
  const voiceMicBtn = document.getElementById('portal-voice-mic');
  const voiceTranscript = document.getElementById('portal-voice-transcript');
  const voiceLogOutput = document.getElementById('portal-voice-output');
  const voiceWaveform = document.getElementById('portal-voice-waveform');

  const voiceScenarios = [
    {
      speech: '"At the Millers. Chucked the leftover lasagna from Tuesday, made 4 portions of braised short ribs. Freeze two, fridge two. Reheat at 350 for 25 minutes covered. They\'re out of olive oil."',
      actions: [
        '✓ Discarded: Tuesday Lasagna (Miller Fridge)',
        '✓ Logged: Braised Short Ribs (2 Frozen, 2 Refrigerator / Glass Container #1 & #2)',
        '✓ Generated: 4x6 Thermal Reheat Label (Oven 350°F · 25 min covered)',
        '✓ Appended: Extra Virgin Olive Oil to Miller upcoming grocery list'
      ]
    },
    {
      speech: '"Costco run complete. 10 lbs prime tenderloin for $120. Split 60% to Miller household, 40% to Davis. Charged on Chef Amex Gold for 4x points."',
      actions: [
        '✓ Split Allocated: Miller Household $72.00 (60%)',
        '✓ Split Allocated: Davis Household $48.00 (40%)',
        '✓ Ledger: Auto-invoiced to client reimbursement accounts',
        '✓ Rewards: +480 Membership Rewards points logged to Chef ledger'
      ]
    },
    {
      speech: '"Generated Coverage Pack for Sarah Jenkins for next Thursday and Friday. Client households: Miller and Henderson. Keycodes and nut allergy warnings locked with password."',
      actions: [
        '✓ Coverage Plan: Generated secure 48-hr expiring link for Sarah Jenkins',
        '✓ Packaged: Miller gate code (#4821), Henderson alarm (#9902)',
        '✓ Highlighted Hazard: Child #2 Severe Tree Nut Allergy (Miller)',
        '✓ Emailed: Complete prep workflow & vendor receipts to Sarah'
      ]
    }
  ];
  let currentScenarioIdx = 0;

  if (voiceMicBtn && voiceTranscript && voiceLogOutput) {
    voiceMicBtn.addEventListener('click', () => {
      voiceMicBtn.style.transform = 'scale(0.92)';
      if (voiceWaveform) voiceWaveform.style.display = 'inline-block';
      voiceTranscript.textContent = 'Listening to kitchen dictation...';
      voiceTranscript.style.fontStyle = 'italic';

      setTimeout(() => {
        voiceMicBtn.style.transform = 'scale(1)';
        if (voiceWaveform) voiceWaveform.style.display = 'none';

        const scenario = voiceScenarios[currentScenarioIdx];
        voiceTranscript.textContent = scenario.speech;
        voiceTranscript.style.fontStyle = 'normal';

        voiceLogOutput.innerHTML = scenario.actions.map(act => `
          <div style="display:flex; align-items:center; gap:8px; font-size:0.88rem; color:#2F4A39; font-weight:700; margin-top:4px;">
            <span>${act}</span>
          </div>
        `).join('');

        currentScenarioIdx = (currentScenarioIdx + 1) % voiceScenarios.length;
      }, 850);
    });
  }

  // 6. Interactive Sample Weekly Meal Plan Data & Tab Switcher (Inspired by Recipeace)
  const mealDataByDay = {
    monday: {
      date: 'Monday, Oct 19',
      cals: '1,560 cal',
      protein: '94g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Cozy Cinnamon Oat Bowl & Sliced Apple',
          meta: '10 min · 380 cal · 14g protein',
          desc: 'Warm rolled oats steeped in almond milk, topped with crisp red apples and a drizzle of honey.',
          tags: ['Pantry Friendly', 'Quick Prep']
        },
        {
          type: 'Lunch',
          title: 'Garden Farro & Lemon Herb Veggie Bowl',
          meta: '20 min · 460 cal · 26g protein',
          desc: 'Toasty farro grains tossed with roasted zucchini, chickpeas, and a bright herb dressing.',
          tags: ['Make Ahead', 'High Fiber']
        },
        {
          type: 'Dinner (Chef Prepped)',
          title: 'Warm Vegetable Noodle Soup with Steamed Dumplings',
          meta: 'Reheat 375°F · 12 min · 720 cal · 54g protein',
          desc: 'Chef prepped in Glass Container #1. Savory carrot-ginger vegetable broth over soft noodles and warm dumplings.',
          tags: ['Chef Prepped', 'Reheat 12 min']
        }
      ]
    },
    tuesday: {
      date: 'Tuesday, Oct 20',
      cals: '1,620 cal',
      protein: '102g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Creamy Avocado & Soft Scrambled Egg Toast',
          meta: '12 min · 420 cal · 22g protein',
          desc: 'Golden toasted sourdough layered with ripe avocado, fluffy eggs, and everything bagel spice.',
          tags: ['High Protein', 'Kid Approved']
        },
        {
          type: 'Lunch',
          title: 'Mediterranean Lentil & Feta Salad',
          meta: '15 min · 480 cal · 28g protein',
          desc: 'Tender brown lentils, crisp cucumbers, kalamata olives, and crumbled feta with red wine vinaigrette.',
          tags: ['No Reheat Needed', 'Prep Sunday']
        },
        {
          type: 'Dinner (Chef Prepped)',
          title: 'Braised Beef Short Ribs & Caramelized Sweet Potatoes',
          meta: 'Reheat 350°F · 25 min covered · 740 cal · 58g protein',
          desc: 'Chef prepped in Glass Container #2. Slow-braised boneless beef short ribs with caramelized root vegetables.',
          tags: ['Chef Prepped', 'Glass Container #2']
        }
      ]
    },
    wednesday: {
      date: 'Wednesday, Oct 21',
      cals: '1,510 cal',
      protein: '88g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Greek Yogurt Parfait with Toasted Walnuts',
          meta: '5 min · 340 cal · 24g protein',
          desc: 'Creamy plain Greek yogurt layered with wild blueberries, raw honey, and crushed walnuts.',
          tags: ['Zero Cook', 'Morning Serenity']
        },
        {
          type: 'Lunch',
          title: 'Toasted Rustic Panini with Mozzarella & Basil',
          meta: '10 min · 510 cal · 26g protein',
          desc: 'Crisp pressed sourdough with sliced heirloom tomatoes, fresh mozzarella, and sweet basil leaves.',
          tags: ['Comfort Classic', 'Vegetarian']
        },
        {
          type: 'Dinner (Family Night)',
          title: 'Coconut Butternut Squash Stew with Jasmine Rice',
          meta: '20 min · 660 cal · 38g protein',
          desc: 'Easy family weeknight dinner on the chef’s off-night. Silky coconut ginger stew with tender squash and peas.',
          tags: ['Family Night', 'Pantry Friendly']
        }
      ]
    },
    thursday: {
      date: 'Thursday, Oct 22',
      cals: '1,580 cal',
      protein: '96g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Green Sunshine Spinach & Banana Smoothie',
          meta: '5 min · 360 cal · 18g protein',
          desc: 'Blended baby spinach, frozen ripe banana, oat milk, chia seeds, and vanilla protein.',
          tags: ['Grab & Go', 'Nutrient Rich']
        },
        {
          type: 'Lunch',
          title: 'Roasted Turkey & Cranberry Wrap',
          meta: '8 min · 460 cal · 34g protein',
          desc: 'Whole grain tortilla filled with oven-roasted turkey slices, baby spinach, and tart cranberry spread.',
          tags: ['Kid Friendly', 'Quick Lunch']
        },
        {
          type: 'Dinner (Chef Prepped)',
          title: 'Baked Wild King Salmon with Garlic Broccolini',
          meta: 'Reheat 375°F · 10 min · 760 cal · 52g protein',
          desc: 'Chef prepped in Glass Container #3. Crisp-skin salmon fillets over tender garlic broccolini with lemon zest.',
          tags: ['Chef Prepped', 'Omega-3 Rich']
        }
      ]
    },
    friday: {
      date: 'Friday, Oct 23',
      cals: '1,680 cal',
      protein: '90g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Fluffy Whole Grain Buttermilk Pancakes',
          meta: '20 min · 440 cal · 16g protein',
          desc: 'Light, fluffy pancakes served with real Vermont maple syrup and a handful of fresh berries.',
          tags: ['Weekend Vibe', 'Family Fun']
        },
        {
          type: 'Lunch',
          title: 'Warm Minestrone Soup with Crusty Baguette',
          meta: '15 min · 460 cal · 22g protein',
          desc: 'Rich tomato broth brimming with white beans, diced carrots, zucchini, and mini shell pasta.',
          tags: ['Pantry Staple', 'Leftover Gold']
        },
        {
          type: 'Dinner (Family Night)',
          title: 'Homemade Peaceful Hearth Flatbread Pizza Night',
          meta: '25 min · 780 cal · 52g protein',
          desc: 'Crispy thin crust flatbread with San Marzano sauce, fresh mozzarella, and personalized toppings for everyone.',
          tags: ['Family Tradition', 'Kid Loved']
        }
      ]
    },
    saturday: {
      date: 'Saturday, Oct 24',
      cals: '1,640 cal',
      protein: '86g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Weekend Garden Vegetable Frittata',
          meta: '25 min · 390 cal · 28g protein',
          desc: 'Cast-iron baked eggs with sweet bell peppers, caramelized leeks, and goat cheese crumbles.',
          tags: ['Brunch Special', 'Make-Ahead']
        },
        {
          type: 'Lunch',
          title: 'Sesame Ginger Soba Noodle Salad',
          meta: '15 min · 490 cal · 20g protein',
          desc: 'Chilled buckwheat noodles tossed in toasted sesame oil, edamame, and crunchy shredded cabbage.',
          tags: ['Crisp & Cool', 'Vegetarian']
        },
        {
          type: 'Dinner (Family Night)',
          title: 'Slow-Simmered Rustic Beef or Mushroom Stew',
          meta: '45 min · 760 cal · 38g protein',
          desc: 'Deeply comforting stew infused with fresh thyme, root vegetables, and thick crusty sourdough for dipping.',
          tags: ['Comfort Food', 'Instills Calm']
        }
      ]
    },
    sunday: {
      date: 'Sunday, Oct 25',
      cals: '1,530 cal',
      protein: '92g protein',
      meals: [
        {
          type: 'Breakfast',
          title: 'Warm Apple Cinnamon Baked Oatmeal',
          meta: '30 min · 410 cal · 18g protein',
          desc: 'Bake once, eat all morning. Spiced apples nestled in golden baked oats with toasted pecans.',
          tags: ['Sunday Ritual', 'Kid Loved']
        },
        {
          type: 'Lunch',
          title: 'Wholesome Rainbow Grain Bowl',
          meta: '15 min · 470 cal · 24g protein',
          desc: 'Quinoa base crowned with roasted carrots, steamed edamame, avocado cubes, and tahini drizzle.',
          tags: ['Vibrant Energy', 'Plant Packed']
        },
        {
          type: 'Dinner (Clear-the-Fridge)',
          title: 'Weekly "Use-It-Up" Pantry Stir-Fry & Jasmine Rice',
          meta: '20 min · 650 cal · 50g protein',
          desc: 'The weekly peace-keeper: clear the crisper drawer with a delicious ginger-soy stir fry and fluffy rice.',
          tags: ['Zero Waste', '15-Min Dinner']
        }
      ]
    }
  };

  const dayTabs = document.querySelectorAll('.day-tab-btn');
  const mealsGrid = document.querySelector('.meals-grid');
  const planDateHeader = document.getElementById('plan-date-header');
  const planAvgCal = document.getElementById('plan-avg-cal');
  const planAvgProtein = document.getElementById('plan-avg-protein');

  function renderDayPlan(dayKey) {
    const data = mealDataByDay[dayKey];
    if (!data || !mealsGrid) return;

    if (planDateHeader) planDateHeader.textContent = data.date;
    if (planAvgCal) planAvgCal.textContent = data.cals;
    if (planAvgProtein) planAvgProtein.textContent = data.protein;

    mealsGrid.innerHTML = data.meals.map(meal => `
      <div class="meal-slot-card">
        <span class="meal-type-pill">${meal.type}</span>
        <h4>${meal.title}</h4>
        <div class="meal-meta">${meal.meta}</div>
        <p style="font-size: 0.92rem; color: var(--text-secondary);">${meal.desc}</p>
        <div class="meal-tags">
          ${meal.tags.map(t => `<span class="tag-badge">${t}</span>`).join('')}
        </div>
      </div>
    `).join('');
  }

  dayTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      dayTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const day = tab.getAttribute('data-day');
      renderDayPlan(day);
    });
  });

  // Initial render of meal plan
  renderDayPlan('monday');

  // 7. FAQ Accordion
  const accordionItems = document.querySelectorAll('.accordion-item');
  accordionItems.forEach(item => {
    const header = item.querySelector('.accordion-header');
    header.addEventListener('click', () => {
      const isOpen = item.classList.contains('active');
      accordionItems.forEach(i => i.classList.remove('active'));
      if (!isOpen) {
        item.classList.add('active');
      }
    });
  });

  // 8. Support Form Simulation
  const supportForm = document.getElementById('support-form');
  const formSuccess = document.getElementById('form-success-message');

  if (supportForm) {
    supportForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const submitBtn = supportForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending with care...';
      }

      setTimeout(() => {
        supportForm.reset();
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send Message';
        }
        if (formSuccess) {
          formSuccess.style.display = 'block';
          setTimeout(() => {
            formSuccess.style.display = 'none';
          }, 6000);
        }
      }, 700);
    });
  }
});
