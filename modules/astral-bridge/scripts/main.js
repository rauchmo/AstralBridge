/* global Roll, game, ui, Hooks, ChatMessage, foundry */
const MODULE_ID = "astral-bridge";
const DND5E_API = "https://www.dnd5eapi.co/api";

// ---------- Label Mappings ----------

const ACTION_LABELS = {
  str: "Strength", dex: "Dexterity", con: "Constitution",
  int: "Intelligence", wis: "Wisdom", cha: "Charisma",
  acrobatics: "Acrobatics", animalhandling: "Animal Handling",
  arcana: "Arcana", athletics: "Athletics", deception: "Deception",
  history: "History", insight: "Insight", intimidation: "Intimidation",
  investigation: "Investigation", medicine: "Medicine", nature: "Nature",
  perception: "Perception", performance: "Performance", persuasion: "Persuasion",
  religion: "Religion", sleightofhand: "Sleight of Hand", stealth: "Stealth",
  survival: "Survival", initiative: "Initiative", death: "Death Save",
};

const ROLL_TYPE_LABELS = {
  check: "Check", save: "Saving Throw", "to hit": "Attack Roll",
  attack: "Attack Roll", damage: "Damage", initiative: "Initiative",
  heal: "Healing", death: "Death Save",
};

const DAMAGE_TYPE_ICONS = {
  acid: "🟢", bludgeoning: "⚫", cold: "❄️", fire: "🔥", force: "🔵",
  lightning: "⚡", necrotic: "💀", piercing: "🗡️", poison: "🟣",
  psychic: "🧠", radiant: "✨", slashing: "⚔️", thunder: "💥",
};

function getRollLabel(action, rollType) {
  const a = action.toLowerCase();
  const t = rollType.toLowerCase();
  const actionLabel = ACTION_LABELS[a] ?? action;

  if (a === "initiative") return "Initiative";
  if (a === "death") return "Death Saving Throw";
  if (t === "to hit" || t === "attack") return `${action} — Attack Roll`;
  if (t === "damage") return `${action} — Damage`;
  if (a === t) return actionLabel;
  return `${actionLabel} ${ROLL_TYPE_LABELS[t] ?? rollType}`;
}

function getRollTypeClass(rollType, action = "") {
  const t = rollType.toLowerCase();
  const a = action.toLowerCase();
  if (a === "initiative" || t === "initiative") return "initiative";
  if (t === "to hit" || t === "attack") return "attack";
  if (t === "damage") return "damage";
  if (t === "heal") return "heal";
  if (t === "save") return "save";
  if (t === "check") return "check";
  return "other";
}

function isCriticalHit(dice, rollType) {
  const t = rollType.toLowerCase();
  if (t !== "to hit" && t !== "attack") return false;
  return dice.some(d => d.faces === 20 && d.result === 20);
}

function formatBreakdown(text) {
  return text.replace(/\+\s*-/g, " - ").replace(/^\+/, "").trim();
}

// ---------- D&D 5e API Lookup ----------

const spellCache = new Map();
const equipCache = new Map();

function toApiIndex(name) {
  return name.toLowerCase().replace(/[^a-z0-9\s]/g, "").trim().replace(/\s+/g, "-");
}

async function lookupSpell(actionName) {
  const index = toApiIndex(actionName);
  if (spellCache.has(index)) return spellCache.get(index);
  try {
    const res = await fetch(`${DND5E_API}/spells/${index}`);
    const spell = res.ok ? await res.json() : null;
    spellCache.set(index, spell);
    if (spell) console.log(`${MODULE_ID} | Found spell: ${spell.name} (${spell.school.name}, Level ${spell.level})`);
    return spell;
  } catch {
    spellCache.set(index, null);
    return null;
  }
}

async function lookupEquipment(actionName) {
  const index = toApiIndex(actionName);
  if (equipCache.has(index)) return equipCache.get(index);
  try {
    const res = await fetch(`${DND5E_API}/equipment/${index}`);
    const item = res.ok ? await res.json() : null;
    // Only keep actual weapons
    if (!item || item.equipment_category?.index !== "weapon") {
    equipCache.set(index, null);
    return null;
  }
  // Generate description if the API doesn't provide one
  if (!item.desc?.length) {
    const dmg      = item.damage?.damage_dice ?? "";
    const dmgType  = item.damage?.damage_type?.name ?? "";
    const dmg2     = item.two_handed_damage?.damage_dice ?? "";
    const props    = (item.properties ?? []).map(p => p.name);
    const range    = item.range ? `Range ${item.range.normal}${item.range.long ? `/${item.range.long}` : ""} ft.` : "";

    const parts = [];
    if (dmg && dmgType) parts.push(`Deals ${dmg} ${dmgType} damage.`);
    if (dmg2)           parts.push(`Versatile: ${dmg2} damage two-handed.`);
    if (range)          parts.push(range);
    if (props.length)   parts.push(`Properties: ${props.join(", ")}.`);

    item.desc = parts.length ? [parts.join(" ")] : [];
  }
  equipCache.set(index, item);
  console.log(`${MODULE_ID} | Found weapon: ${item.name} (${item.weapon_category})`);
  return item;
  } catch {
    equipCache.set(index, null);
    return null;
  }
}

// Normalise spell/equipment into a common shape for buildFlavor
async function lookupApiInfo(actionName, rollType) {
  const t = rollType.toLowerCase();
  if (t !== "to hit" && t !== "damage" && t !== "attack") return null;

  const spell = await lookupSpell(actionName);
  if (spell) {
    const levelLabel = spellLevelLabel(spell.level);
    const school     = spell.school?.name ?? "";
    const dmgType    = spell.damage?.damage_type?.name ?? "";
    const dmgIcon    = dmgType ? (DAMAGE_TYPE_ICONS[dmgType.toLowerCase()] ?? "🎲") : "";
    const saveType   = spell.dc?.dc_type?.name ?? "";

    const tags = [[levelLabel, school].filter(Boolean).join(" ")];
    if (dmgType) tags.push(`${dmgIcon} ${dmgType}`);
    if (saveType && t !== "damage") tags.push(`${saveType} Save`);

    return { tags, desc: firstSentence(spell.desc?.[0] ?? "") };
  }

  const equip = await lookupEquipment(actionName);
  if (equip) {
    const dmgType  = equip.damage?.damage_type?.name ?? "";
    const dmgDice  = equip.damage?.damage_dice ?? "";
    const dmgIcon  = dmgType ? (DAMAGE_TYPE_ICONS[dmgType.toLowerCase()] ?? "⚔️") : "⚔️";
    const category = equip.weapon_category ?? "";
    const props    = (equip.properties ?? []).map(p => p.name).slice(0, 3);

    const tags = [];
    if (category) tags.push(category);
    if (dmgType)  tags.push(`${dmgIcon} ${dmgType}${dmgDice ? ` (${dmgDice})` : ""}`);
    tags.push(...props);

    return { tags, desc: firstSentence(equip.desc?.[0] ?? "") };
  }

  return null;
}

function spellLevelLabel(level) {
  if (level === 0) return "Cantrip";
  const ordinals = ["", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th"];
  return `${ordinals[level] ?? level} Level`;
}

function firstSentence(text, maxLen = 160) {
  if (!text) return "";
  const match = text.match(/^[^.!?]+[.!?]/);
  const s = match ? match[0].trim() : text.trim();
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
}

// ---------- Settings ----------

Hooks.once("init", () => {
  game.settings.register(MODULE_ID, "bridgeUrl", {
    name: "Bridge WebSocket URL",
    hint: "URL of the Python bridge server (e.g. ws://10.130.0.2:8765)",
    scope: "world", config: true, type: String,
    default: "ws://localhost:8765/ws",
  });

  game.settings.register(MODULE_ID, "rollMode", {
    name: "Roll Mode",
    hint: "How D&D Beyond rolls are displayed in chat.",
    scope: "world", config: true, type: String,
    choices: {
      publicroll: "Public Roll", gmroll: "GM Roll",
      blindroll: "Blind GM Roll", selfroll: "Self Roll",
    },
    default: "publicroll",
  });

  game.settings.register(MODULE_ID, "showDiceSoNice", {
    name: "Dice So Nice — 3D Dice Animation",
    hint: "Show Dice So Nice 3D dice animations for D&D Beyond rolls. Disable if you don't want the animations when rolls come in from DDB.",
    scope: "world", config: true, type: Boolean,
    default: true,
  });

  game.settings.register(MODULE_ID, "autoInitiative", {
    name: "Auto-set Initiative",
    hint: "Automatically update the combat tracker when rolling Initiative in D&D Beyond.",
    scope: "world", config: true, type: Boolean,
    default: true,
  });

  game.settings.register(MODULE_ID, "autoAnimations", {
    name: "Automated Animations",
    hint: "Trigger Automated Animations when a D&D Beyond attack roll hits. Requires the Automated Animations module.",
    scope: "world", config: true, type: Boolean,
    default: true,
  });

  game.settings.register(MODULE_ID, "hpSync", {
    name: "HP Sync — DDB ↔ Foundry",
    hint: "Compare max HP from D&D Beyond with the Foundry actor and notify if they differ. Allows auto-update.",
    scope: "world", config: true, type: Boolean,
    default: false,
  });

  game.settings.register(MODULE_ID, "damageConfirm", {
    name: "Damage Confirmation Dialog",
    hint: "Show a confirmation popup before applying damage, with options to double (crit), change targets, or cancel.",
    scope: "world", config: true, type: Boolean,
    default: true,
  });

  game.settings.register(MODULE_ID, "floatingNumbers", {
    name: "Floating Damage / Heal Numbers",
    hint: "Show floating numbers on tokens when damage or healing is applied. Requires the Sequencer module.",
    scope: "world", config: true, type: Boolean,
    default: true,
  });
});

// ---------- Bridge Connection ----------

let socket = null;

Hooks.once("ready", () => {
  if (!game.user.isGM) return;
  connectBridge(game.settings.get(MODULE_ID, "bridgeUrl"));
});

function connectBridge(url) {
  console.log(`${MODULE_ID} | Connecting to bridge at ${url}...`);
  socket = new WebSocket(url);

  socket.addEventListener("open", () => {
    console.log(`${MODULE_ID} | Connected to bridge.`);
    ui.notifications.info("AstralBridge connected.");
  });

  socket.addEventListener("message", async (event) => {
    let data;
    try { data = JSON.parse(event.data); }
    catch (e) { console.error(`${MODULE_ID} | Bad message:`, event.data); return; }

    if (data.type === "ddb-roll") {
      try { await handleRoll(data); }
      catch (err) { console.error(`${MODULE_ID} | handleRoll error:`, err); }
    }
  });

  socket.addEventListener("close", () => {
    console.warn(`${MODULE_ID} | Disconnected. Reconnecting in 5s...`);
    socket = null;
    setTimeout(() => connectBridge(game.settings.get(MODULE_ID, "bridgeUrl")), 5000);
  });

  socket.addEventListener("error", (err) => console.error(`${MODULE_ID} | Error:`, err));
}

function sendToBridge(payload) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

// ---------- Combat Turn Tracking ----------

// ---------- Combat Turn Tracking ----------

Hooks.on("combatTurn", (combat, updateData) => { _handleCombatAdvance(combat, updateData); });
Hooks.on("combatRound", (combat, updateData) => { _handleCombatAdvance(combat, updateData); });

function _handleCombatAdvance(combat, updateData) {
  if (!game.user.isGM) return;
  // combat.combatant reflects the OLD turn when the hook fires — use updateData for the new index
  const newTurn   = updateData?.turn  ?? combat.turn;
  const newRound  = updateData?.round ?? combat.round;
  const combatant = combat.turns[newTurn];
  if (!combatant) return;
  const character = combatant.actor?.name ?? combatant.name ?? "";
  sendToBridge({ type: "combat-turn", character, round: newRound, turn: newTurn });
}

// ---------- Target Picker ----------

async function pickTarget(character, total, isCrit) {
  const allTokens = (canvas.tokens?.placeables ?? []).filter(t => t.actor && t.actor.name !== character);
  if (!allTokens.length) return null;

  // Pre-select tokens the user has already manually targeted in Foundry
  const manualTargetIds = new Set([...(game.user.targets ?? [])].map(t => t.id));

  return new Promise(resolve => {
    const rows = allTokens.map(t => {
      const ac         = t.actor.system?.attributes?.ac?.value ?? "?";
      const img        = t.document.texture?.src ?? "icons/svg/mystery-man.svg";
      const preChecked = manualTargetIds.has(t.id) ? "checked" : "";
      return `
        <label style="display:flex;align-items:center;gap:8px;padding:6px 8px;
          border:1px solid #c9c4b3;border-radius:4px;cursor:pointer;margin-bottom:4px;
          background:#f9f6ee;" onmouseover="this.style.background='#ede9dc'"
          onmouseout="this.style.background='#f9f6ee'">
          <input type="checkbox" name="ddb-target" value="${t.id}" ${preChecked} style="flex-shrink:0;">
          <img src="${img}" style="width:28px;height:28px;border-radius:3px;object-fit:cover;border:1px solid #c9c4b3;">
          <span style="flex:1;font-weight:600;">${t.name}</span>
          <span style="color:#666;font-size:0.85em;flex-shrink:0;">AC&nbsp;${ac}</span>
        </label>`;
    }).join("");

    const hitLabel = isCrit ? "★ CRIT — auto HIT!" : `Roll: <strong>${total}</strong>`;

    const content = `
      <div style="font-family:Georgia,serif;padding:4px 0 8px 0;">
        <p style="margin-bottom:10px;font-size:0.92em;">
          <strong>${character}</strong> attacks — ${hitLabel}
        </p>
        ${rows}
      </div>`;

    new Dialog({
      title: "Choose Attack Target(s)",
      content,
      buttons: {
        attack: {
          icon:  '<i class="fas fa-crosshairs"></i>',
          label: "Confirm",
          callback: html => {
            const checkedIds = [...html.find("input[name='ddb-target']:checked")].map(el => el.value);
            const targets = allTokens
              .filter(t => checkedIds.includes(t.id))
              .map(t => {
                const ac  = t.actor.system?.attributes?.ac?.value ?? null;
                const hit = isCrit || (ac !== null ? total >= ac : null);
                return { name: t.name, ac, hit, tokenId: t.id };
              });
            resolve(targets.length ? targets : null);
          },
        },
        forceHit: {
          icon:  '<i class="fas fa-check-double"></i>',
          label: "Force Hit",
          callback: html => {
            const checkedIds = [...html.find("input[name='ddb-target']:checked")].map(el => el.value);
            const targets = allTokens
              .filter(t => checkedIds.includes(t.id))
              .map(t => {
                const ac = t.actor.system?.attributes?.ac?.value ?? null;
                return { name: t.name, ac, hit: true, tokenId: t.id };
              });
            resolve(targets.length ? targets : null);
          },
        },
        skip: { label: "No Target", callback: () => resolve(null) },
      },
      default: "attack",
    }, { width: 320 }).render(true);
  });
}

// ---------- Automated Animations ----------

async function showFloatingNumbers(results, isHeal = false, isCrit = false) {
  if (!game.settings.get(MODULE_ID, "floatingNumbers")) return;
  if (!game.modules.get("sequencer")?.active) return;
  if (!results?.length) return;

  for (const r of results) {
    const token = (canvas.tokens?.placeables ?? []).find(t => t.id === r.tokenId);
    if (!token) continue;

    const amount = isHeal ? r.healed : r.damage;
    const text   = isHeal ? `+${amount}` : `-${amount}`;
    const color  = isHeal ? "#56d364" : (isCrit ? "#e3b341" : "#f85149");

    new Sequence()
      .scrollingText(token, text, {
        duration:        1800,
        distance:        120,
        fontSize:        isCrit ? 64 : 48,
        color,
        stroke:          "#000000",
        strokeThickness: 4,
        jitter:          0.2,
      })
      .play();
  }
}

async function triggerAutoAnimations(character, action, targetTokens) {
  if (!game.settings.get(MODULE_ID, "autoAnimations")) return;
  if (!game.modules.get("autoanimations")?.active) return;
  if (!targetTokens.length) return;

  const sourceToken = canvas.tokens?.placeables?.find(t => t.actor?.name === character);
  if (!sourceToken) return;

  // Prefer the real item from the actor so AA can match its database entries
  const item = sourceToken.actor?.items?.find(
    i => i.name.toLowerCase() === action.toLowerCase()
  ) ?? { name: action };

  try {
    // AutoAnimations (v6) deprecated API still accepts explicit targets
    if (typeof AutoAnimations !== "undefined") {
      await AutoAnimations.playAnimation(sourceToken, targetTokens, item);
    } else if (typeof AutomatedAnimations !== "undefined") {
      // Newer API: set targets on the user first, then call
      const prevTargets = [...game.user.targets].map(t => t.id);
      await game.user.updateTokenTargets(targetTokens.map(t => t.id));
      await AutomatedAnimations.playAnimation(sourceToken, item);
      await game.user.updateTokenTargets(prevTargets);
    }
    console.log(`${MODULE_ID} | AutoAnimations triggered: ${action} → ${targetTokens.map(t => t.name).join(", ")}`);
  } catch (err) {
    console.warn(`${MODULE_ID} | AutoAnimations trigger failed:`, err);
  }
}

// ---------- Heal Target Picker ----------

async function pickHealTargets(character, amount) {
  const allTokens = (canvas.tokens?.placeables ?? []).filter(t => t.actor);
  if (!allTokens.length) return null;

  const manualTargetIds = new Set([...(game.user.targets ?? [])].map(t => t.id));

  return new Promise(resolve => {
    const rows = allTokens.map(t => {
      const hp         = t.actor.system?.attributes?.hp;
      const cur        = hp?.value ?? "?";
      const max        = hp?.max   ?? "?";
      const img        = t.document.texture?.src ?? "icons/svg/mystery-man.svg";
      const preChecked = manualTargetIds.has(t.id) ? "checked" : "";
      return `
        <label style="display:flex;align-items:center;gap:8px;padding:6px 8px;
          border:1px solid #c9c4b3;border-radius:4px;cursor:pointer;margin-bottom:4px;
          background:#f9f6ee;" onmouseover="this.style.background='#ede9dc'"
          onmouseout="this.style.background='#f9f6ee'">
          <input type="checkbox" name="ddb-heal-target" value="${t.id}" ${preChecked} style="flex-shrink:0;">
          <img src="${img}" style="width:28px;height:28px;border-radius:3px;object-fit:cover;border:1px solid #c9c4b3;">
          <span style="flex:1;font-weight:600;">${t.name}</span>
          <span style="color:#2ea043;font-size:0.85em;flex-shrink:0;">HP ${cur} / ${max}</span>
        </label>`;
    }).join("");

    const content = `
      <div style="font-family:Georgia,serif;padding:4px 0 8px 0;">
        <p style="margin-bottom:10px;font-size:0.92em;">
          <strong>${character}</strong> heals <strong style="color:#2ea043;">+${amount} HP</strong> — choose target(s)
        </p>
        ${rows}
      </div>`;

    new Dialog({
      title: "Choose Heal Target(s)",
      content,
      buttons: {
        heal: {
          icon: '<i class="fas fa-heart"></i>',
          label: "Heal",
          callback: html => {
            const checkedIds = [...html.find("input[name='ddb-heal-target']:checked")].map(el => el.value);
            const targets = allTokens
              .filter(t => checkedIds.includes(t.id))
              .map(t => ({ name: t.name, tokenId: t.id }));
            resolve(targets.length ? targets : null);
          },
        },
        skip: { label: "Skip", callback: () => resolve(null) },
      },
      default: "heal",
    }, { width: 320 }).render(true);
  });
}

async function applyHealingToTargets(targets, amount) {
  const results = [];
  for (const target of targets) {
    const token = (canvas.tokens?.placeables ?? []).find(t => t.id === target.tokenId);
    if (!token?.actor) continue;
    const hp = token.actor.system?.attributes?.hp;
    if (!hp) continue;
    const oldHp  = hp.value;
    const maxHp  = hp.max;
    const newHp  = Math.min(maxHp, oldHp + amount);
    const healed = newHp - oldHp;
    if (healed > 0) await token.actor.update({ "system.attributes.hp.value": newHp });
    console.log(`${MODULE_ID} | Healing applied: ${target.name} HP ${oldHp} → ${newHp} (+${healed})`);
    results.push({ targetName: target.name, oldHp, newHp, maxHp, healed, tokenId: token.id });
  }
  return results.length ? results : null;
}

// ---------- Hit Tracking ----------

// Stores hit targets per character: Map<characterName, [{name, ac, tokenId}]>
const pendingDamageTarget = new Map();

async function applyDirectDamage(targets, damage) {
  const results = [];
  for (const target of targets) {
    const token = (canvas.tokens?.placeables ?? []).find(t => t.id === target.tokenId);
    if (!token?.actor) continue;
    const hp = token.actor.system?.attributes?.hp;
    if (!hp) continue;
    const oldHp = hp.value;
    const newHp = Math.max(0, oldHp - damage);
    await token.actor.update({ "system.attributes.hp.value": newHp });
    console.log(`${MODULE_ID} | Damage applied: ${target.name} HP ${oldHp} → ${newHp} (−${damage})`);
    results.push({ targetName: target.name, oldHp, newHp, damage, tokenId: token.id });
  }
  return results.length ? results : null;
}

// ---------- Damage Picker + Confirmation (unified) ----------

async function pickAndConfirmDamage(character, amount, isCrit, preSelectedIds) {
  const allTokens = (canvas.tokens?.placeables ?? []).filter(t => t.actor);

  // If confirm dialog disabled: skip dialog, apply to pre-selected targets directly
  if (!game.settings.get(MODULE_ID, "damageConfirm")) {
    const targets = allTokens
      .filter(t => preSelectedIds.includes(t.id))
      .map(t => ({ name: t.name, tokenId: t.id }));
    return targets.length ? { targets, amount } : null;
  }

  const preSelectedSet = new Set(preSelectedIds);

  return new Promise(resolve => {
    const buildContent = (currentAmount) => {
      const rows = allTokens.map(t => {
        const hp  = t.actor.system?.attributes?.hp;
        const cur = hp?.value ?? "?";
        const max = hp?.max   ?? "?";
        const img = t.document.texture?.src ?? "icons/svg/mystery-man.svg";
        const checked = preSelectedSet.has(t.id) ? "checked" : "";
        return `
          <label style="display:flex;align-items:center;gap:8px;padding:6px 8px;
            border:1px solid #30363d;border-radius:4px;cursor:pointer;margin-bottom:4px;
            background:#161b22;" onmouseover="this.style.background='#21262d'"
            onmouseout="this.style.background='#161b22'">
            <input type="checkbox" name="ddb-dmg-target" value="${t.id}" ${checked} style="flex-shrink:0;accent-color:#f85149;">
            <img src="${img}" style="width:28px;height:28px;border-radius:3px;object-fit:cover;border:1px solid #30363d;">
            <span style="flex:1;font-weight:600;color:#f0f6fc;">${t.name}</span>
            <span style="color:#8b949e;font-size:0.82em;flex-shrink:0;">HP ${cur} / ${max}</span>
          </label>`;
      }).join("");

      return `
        <div style="font-family:'Segoe UI',system-ui,sans-serif;padding:4px 0;">
          <div style="font-size:2.2em;font-weight:700;color:#f85149;text-align:center;margin-bottom:4px;line-height:1.1;">
            ${currentAmount}
            ${isCrit ? "<span style='font-size:0.45em;color:#e3b341;vertical-align:middle;margin-left:6px;'>CRIT</span>" : ""}
          </div>
          <div style="text-align:center;color:#8b949e;font-size:0.8em;margin-bottom:14px;">damage — select targets</div>
          <div style="max-height:260px;overflow-y:auto;">${rows}</div>
        </div>`;
    };

    const showDialog = (currentAmount) => {
      new Dialog({
        title: `Damage — ${character}`,
        content: buildContent(currentAmount),
        buttons: {
          apply: {
            icon: '<i class="fas fa-check"></i>',
            label: `Apply ${currentAmount}`,
            callback: html => {
              const checkedIds = [...html.find("input[name='ddb-dmg-target']:checked")].map(el => el.value);
              const targets = allTokens.filter(t => checkedIds.includes(t.id)).map(t => ({ name: t.name, tokenId: t.id }));
              resolve(targets.length ? { targets, amount: currentAmount } : null);
            },
          },
          double: {
            icon: '<i class="fas fa-2x"></i>',
            label: `Double → ${currentAmount * 2}`,
            callback: html => {
              const checkedIds = [...html.find("input[name='ddb-dmg-target']:checked")].map(el => el.value);
              const targets = allTokens.filter(t => checkedIds.includes(t.id)).map(t => ({ name: t.name, tokenId: t.id }));
              resolve(targets.length ? { targets, amount: currentAmount * 2 } : null);
            },
          },
          cancel: {
            icon: '<i class="fas fa-ban"></i>',
            label: "Cancel",
            callback: () => resolve(null),
          },
        },
        default: "apply",
        close: () => resolve(null),
      }, { width: 360 }).render(true);
    };

    showDialog(amount);
  });
}

// ---------- Initiative ----------

async function updateInitiative(character, value) {
  if (!game.settings.get(MODULE_ID, "autoInitiative")) return;
  if (!game.combat) {
    console.log(`${MODULE_ID} | No active combat — initiative not set.`);
    return;
  }

  const actor = game.actors.find(a => a.name === character);
  if (!actor) {
    console.warn(`${MODULE_ID} | Actor "${character}" not found.`);
    return;
  }

  const combatant = game.combat.combatants.find(c => c.actorId === actor.id);
  if (!combatant) {
    ui.notifications?.warn(`AstralBridge: ${character} is not in the combat tracker.`);
    console.warn(`${MODULE_ID} | ${character} not found in combat tracker.`);
    return;
  }

  await game.combat.setInitiative(combatant.id, value);
  ui.notifications?.info(`Initiative set: ${character} → ${value}`);
  console.log(`${MODULE_ID} | Initiative set: ${character} = ${value}`);
}

// ---------- HP Sync ----------

const _syncedCharacters = new Set();

async function syncHpFromDDB(character, entityId) {
  if (!game.settings.get(MODULE_ID, "hpSync")) return;
  if (!entityId || _syncedCharacters.has(entityId)) return;
  _syncedCharacters.add(entityId);

  const bridgeUrl = game.settings.get(MODULE_ID, "bridgeUrl")
    .replace("ws://", "http://").replace("wss://", "https://").replace("/ws", "");

  try {
    const res = await fetch(`${bridgeUrl}/api/character/${entityId}`);
    if (!res.ok) return;
    const ddb = await res.json();
    if (!ddb.max_hp) return;

    const actor = game.actors.find(a => a.name === character);
    if (!actor) return;

    const foundryMax = actor.system?.attributes?.hp?.max;
    if (foundryMax === ddb.max_hp) return;

    // HP mismatch — ask user
    const choice = await Dialog.confirm({
      title: "HP Sync — AstralBridge",
      content: `
        <div style="font-family:'Segoe UI',sans-serif;padding:4px 0;">
          <p style="margin-bottom:10px;">Max HP mismatch for <strong>${character}</strong>:</p>
          <div style="display:flex;gap:16px;justify-content:center;margin-bottom:10px;">
            <div style="text-align:center;">
              <div style="font-size:1.8em;font-weight:700;color:#4f9eff;">${foundryMax}</div>
              <div style="font-size:0.75em;color:#8b949e;">Foundry</div>
            </div>
            <div style="font-size:1.5em;color:#8b949e;align-self:center;">→</div>
            <div style="text-align:center;">
              <div style="font-size:1.8em;font-weight:700;color:#34d068;">${ddb.max_hp}</div>
              <div style="font-size:0.75em;color:#8b949e;">D&D Beyond</div>
            </div>
          </div>
          <p style="font-size:0.85em;color:#8b949e;">Update Foundry to match D&D Beyond?</p>
        </div>`,
      yes: { label: "Update", icon: '<i class="fas fa-sync"></i>' },
      no:  { label: "Keep",   icon: '<i class="fas fa-times"></i>' },
    });

    if (choice) {
      await actor.update({ "system.attributes.hp.max": ddb.max_hp });
      ui.notifications?.info(`AstralBridge: ${character} max HP updated ${foundryMax} → ${ddb.max_hp}`);
    }
  } catch (_) {
    // silently ignore HP sync errors
  }
}

// ---------- Roll Handling ----------

async function handleRoll(data) {
  const { character, action, rollType, total, text, dice = [], constant = 0, entity_id } = data;
  const label = getRollLabel(action, rollType);
  const crit = isCriticalHit(dice, rollType);

  const t          = rollType.toLowerCase();
  const isAttack   = t === "to hit" || t === "attack";
  const isDamage   = t === "damage";
  const isHeal     = t === "heal";
  const isInitiative = action.toLowerCase() === "initiative";

  if (isInitiative) updateInitiative(character, total).catch(console.warn);
  if (entity_id) syncHpFromDDB(character, entity_id).catch(console.warn);

  const [apiInfo, targetResult] = await Promise.all([
    lookupApiInfo(action, rollType),
    isAttack ? pickTarget(character, total, crit) : Promise.resolve(null),
  ]);

  // Heal flow: pick targets → apply HP
  const healTargets = isHeal ? await pickHealTargets(character, total) : null;
  const healResults = healTargets ? await applyHealingToTargets(healTargets, total) : null;

  // Store hit targets for upcoming damage roll, clear on miss
  if (isAttack && targetResult) {
    const hitTargets = targetResult.filter(t => t.hit);
    if (hitTargets.length) pendingDamageTarget.set(character, hitTargets);
    else pendingDamageTarget.delete(character);
  }

  // Damage flow: unified picker + confirm dialog
  let damageResults = null;
  if (isDamage) {
    // Pre-select hit targets (weapon) or manually targeted tokens (spell)
    const storedHits   = pendingDamageTarget.get(character) ?? [];
    const preSelectedIds = storedHits.length
      ? storedHits.map(t => t.tokenId)
      : [...(game.user.targets ?? [])].map(t => t.id);
    pendingDamageTarget.delete(character);

    const confirmed = await pickAndConfirmDamage(character, total, crit, preSelectedIds);
    if (confirmed) {
      damageResults = await applyDirectDamage(confirmed.targets, confirmed.amount);
    }
  }

  // Trigger AA for damage and heals
  if (isDamage && damageResults) {
    const tokens = (canvas.tokens?.placeables ?? []).filter(t => damageResults.some(r => r.tokenId === t.id));
    triggerAutoAnimations(character, action, tokens).catch(console.warn);
  }
  if (isHeal && healResults) {
    const tokens = (canvas.tokens?.placeables ?? []).filter(t => healResults.some(r => r.tokenId === t.id));
    triggerAutoAnimations(character, action, tokens).catch(console.warn);
  }

  // Floating numbers for damage and heals
  if (damageResults) showFloatingNumbers(damageResults, false, crit).catch(console.warn);
  if (healResults)   showFloatingNumbers(healResults,   true,  false).catch(console.warn);

  const targetLog = targetResult ? targetResult.map(t => `${t.name}(AC${t.ac})${t.hit ? "HIT" : "MISS"}`).join(", ") : "";
  const dmgLog    = damageResults ? damageResults.map(r => `−${r.damage} to ${r.targetName}`).join(", ") : "";
  const healLog   = healResults   ? healResults.map(r => `+${r.healed} to ${r.targetName}`).join(", ") : "";
  console.log(`${MODULE_ID} | ${character}: ${label} = ${total}${crit ? " [CRIT!]" : ""}${targetLog ? ` → ${targetLog}` : ""}${dmgLog ? ` | ${dmgLog}` : ""}${healLog ? ` | ${healLog}` : ""}`);

  const roll = await buildRoll(dice, constant, total);

  const actor = game.actors.find(a => a.name === character);
  const speaker = actor ? ChatMessage.getSpeaker({ actor }) : { alias: character };
  const flavor = buildFlavor(label, text, rollType, crit, apiInfo, targetResult, damageResults, healResults, action);
  const rollMode = game.settings.get(MODULE_ID, "rollMode");
  const showDSN = game.settings.get(MODULE_ID, "showDiceSoNice");

  if (!showDSN && game.dice3d) game.dice3d.messageHookDisabled = true;
  await roll.toMessage({ speaker, flavor }, { rollMode });
  if (!showDSN && game.dice3d) game.dice3d.messageHookDisabled = false;
}

function buildFlavor(label, text, rollType, isCrit, apiInfo, targetResult = null, damageResults = null, healResults = null, action = "") {
  const TYPE_ACCENTS = {
    attack:     "#c0392b",
    damage:     "#b8860b",
    heal:       "#1a7a3a",
    save:       "#1a4fa0",
    check:      "#1a7a3a",
    initiative: "#6a3fa0",
    other:      "#555566",
  };
  const typeKey = getRollTypeClass(rollType, action);
  const accent = TYPE_ACCENTS[typeKey] ?? TYPE_ACCENTS.other;
  const breakdown = formatBreakdown(text);

  const critBadge = isCrit
    ? `<span style="font-size:0.65em;background:#fff3cd;color:#856404;
        border:1px solid #ffc107;border-radius:3px;padding:1px 7px;
        font-weight:700;letter-spacing:0.06em;">★ CRIT</span>` : "";

  const ddbBadge = `<span style="font-size:0.63em;background:rgba(0,0,0,0.06);color:#666;
    border:1px solid rgba(0,0,0,0.15);border-radius:3px;padding:1px 6px;font-weight:600;
    letter-spacing:0.04em;">DDB</span>`;

  let spellSection = "";
  if (apiInfo) {
    const tagHtml = apiInfo.tags.map(t =>
      `<span style="font-size:0.68em;background:rgba(0,0,0,0.05);border:1px solid rgba(0,0,0,0.15);
        border-radius:3px;padding:1px 6px;color:#444;white-space:nowrap;">${t}</span>`
    ).join("");
    spellSection = `
      <div style="display:flex;flex-wrap:wrap;gap:3px;margin:5px 0 3px 0;">${tagHtml}</div>
      ${apiInfo.desc ? `<div style="font-size:0.82em;font-style:italic;line-height:1.55;margin:4px 0;
        padding:6px 9px;background:rgba(0,0,0,0.04);border-left:2px solid rgba(0,0,0,0.15);
        border-radius:0 4px 4px 0;color:#555;">${apiInfo.desc}</div>` : ""}`;
  }

  const breakdownHtml = breakdown
    ? `<div style="font-size:0.82em;color:#666;font-style:italic;margin-top:3px;">${breakdown}</div>`
    : "";

  let targetHtml = "";
  if (targetResult?.length) {
    const rows = targetResult.map(tr => {
      const hit     = tr.hit;
      const unknown = hit === null;
      const bdr   = unknown ? "rgba(0,0,0,0.1)" : hit ? "#1a7a3a" : "rgba(0,0,0,0.1)";
      const col   = unknown ? "#666" : hit ? "#1a7a3a" : "#c0392b";
      const icon  = (isCrit || hit) ? (isCrit ? "★ CRIT" : "✓ HIT") : "✗ MISS";
      const acStr = tr.ac !== null ? `<span style="color:#888;margin-left:4px;font-size:0.9em;">AC ${tr.ac}</span>` : "";
      return `<div style="display:flex;align-items:center;justify-content:space-between;
        padding:4px 8px;background:rgba(0,0,0,0.04);border:1px solid ${bdr};border-radius:4px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="font-weight:700;font-size:0.82em;color:${col};letter-spacing:0.04em;">${icon}</span>
          <span style="font-size:0.85em;color:#333;">${tr.name}</span>
        </div>
        ${acStr}
      </div>`;
    }).join("");
    targetHtml = `<div style="display:flex;flex-direction:column;gap:3px;margin-top:6px;">${rows}</div>`;
  }

  let damageHtml = "";
  if (damageResults?.length) {
    const bars = damageResults.map(r => {
      const pct = Math.round((r.newHp / Math.max(r.oldHp, 1)) * 100);
      const barCol = pct > 50 ? "#1a7a3a" : pct > 25 ? "#b8860b" : "#c0392b";
      return `<div style="padding:5px 8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-size:0.82em;color:#333;">${r.targetName}</span>
          <span style="font-size:0.82em;font-weight:700;color:#c0392b;">−${r.damage} HP</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          <div style="flex:1;height:4px;background:rgba(0,0,0,0.1);border-radius:4px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:${barCol};border-radius:4px;transition:width 0.3s;"></div>
          </div>
          <span style="font-size:0.7em;color:#888;flex-shrink:0;font-variant-numeric:tabular-nums;">${r.newHp} / ${r.oldHp}</span>
        </div>
      </div>`;
    }).join("");
    damageHtml = `<div style="margin-top:6px;background:rgba(0,0,0,0.03);
      border:1px solid rgba(0,0,0,0.1);border-radius:5px;">${bars}</div>`;
  }

  let healHtml = "";
  if (healResults?.length) {
    const bars = healResults.map(r => {
      const pct = Math.round((r.newHp / Math.max(r.maxHp, 1)) * 100);
      const barCol = pct > 50 ? "#1a7a3a" : pct > 25 ? "#b8860b" : "#c0392b";
      return `<div style="padding:5px 8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-size:0.82em;color:#333;">${r.targetName}</span>
          <span style="font-size:0.82em;font-weight:700;color:#1a7a3a;">+${r.healed} HP</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          <div style="flex:1;height:4px;background:rgba(0,0,0,0.1);border-radius:4px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:${barCol};border-radius:4px;"></div>
          </div>
          <span style="font-size:0.7em;color:#888;flex-shrink:0;font-variant-numeric:tabular-nums;">${r.newHp} / ${r.maxHp}</span>
        </div>
      </div>`;
    }).join("");
    healHtml = `<div style="margin-top:6px;background:rgba(0,0,0,0.03);
      border:1px solid rgba(0,0,0,0.1);border-radius:5px;">${bars}</div>`;
  }

  return `
    <div style="padding:6px 8px 6px 10px;border-left:3px solid ${accent};border-radius:0 5px 5px 0;margin:1px 0;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
        <strong style="font-size:0.92em;color:#1a1a2e;line-height:1.4;flex:1;">${label}</strong>
        <div style="display:flex;gap:4px;align-items:center;flex-shrink:0;">
          ${critBadge}${ddbBadge}
        </div>
      </div>
      ${spellSection}
      ${breakdownHtml}
      ${targetHtml}
      ${damageHtml}
      ${healHtml}
    </div>`;
}

// ---------- Roll Construction ----------

async function buildRoll(dice, constant, total) {
  const groups = {};
  for (const d of dice) groups[d.faces] = (groups[d.faces] ?? 0) + 1;

  const parts = Object.entries(groups).map(([f, c]) => `${c}d${f}`);
  if (constant > 0) parts.push(`${constant}`);
  else if (constant < 0) parts.push(`${constant}`);

  const formula = parts.length > 0 ? parts.join(" + ") : `${Math.max(total, 0)}`;

  const roll = new Roll(formula);
  await roll.evaluate();

  const DieTerm = foundry.dice?.terms?.Die ?? Die; // v13+ namespaced, fallback for older
  let dieIndex = 0;
  for (const term of roll.terms) {
    if (term instanceof DieTerm) {
      for (const result of term.results) {
        if (dieIndex < dice.length) {
          result.result = dice[dieIndex].result;
          dieIndex++;
        }
      }
    }
  }

  roll._total = total;
  return roll;
}
