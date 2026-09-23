// Copyright (c) 2026 Tyler Fursman
//
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict'

const mineflayer = require('mineflayer')

const [host, port, version, scenario, username] = process.argv.slice(2)

const RESULT = 0
const CENTER = 5
const OUTER = [1, 2, 3, 4, 6, 7, 8, 9]
const GRID = [1, 2, 3, 4, 5, 6, 7, 8, 9]

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

async function waitFor (check, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const value = check()
    if (value) return value
    await sleep(50)
  }
  return check()
}

function report (result) {
  console.log('RESULT ' + JSON.stringify(result))
}

const bot = mineflayer.createBot({ host, port: Number(port), username, version, auth: 'offline' })

// ViaProxy mangles routine movement packets for some targets (26.3), and the
// test never moves, so the harness can drop them. Teleport replies still go out.
if (process.env.MCTEST_NO_MOVEMENT === '1') {
  const write = bot._client.write.bind(bot._client)
  bot._client.write = (name, params) => {
    if (name === 'position' || name === 'look' || name === 'flying') return
    return write(name, params)
  }
}
const legacy = () => bot.registry.version['<']('1.13')

function isGoldenApple (item) {
  return !!item && item.name === 'golden_apple' && (!legacy() || item.metadata === 0)
}

function isEnchantedApple (item) {
  if (!item) return false
  return legacy() ? item.name === 'golden_apple' && item.metadata === 1 : item.name === 'enchanted_golden_apple'
}

function describe (window, slots) {
  return slots.map(slot => {
    const item = window.slots[slot]
    return item ? `${slot}:${item.name}${item.metadata ? '@' + item.metadata : ''}x${item.count}` : `${slot}:-`
  })
}

async function give (name, count) {
  const before = bot.inventory.items().filter(i => i.name === name).reduce((n, i) => n + i.count, 0)
  bot.chat(legacy() ? `/give ${username} minecraft:${name} ${count} 0` : `/give ${username} minecraft:${name} ${count}`)
  const ok = await waitFor(() => bot.inventory.items().filter(i => i.name === name).reduce((n, i) => n + i.count, 0) >= before + count, 5000)
  if (!ok) throw new Error(`/give ${name} ${count} did not arrive`)
}

async function openCraftingTable () {
  const pos = bot.entity.position.floored().offset(2, 0, 0)
  bot.chat(`/setblock ${pos.x} ${pos.y} ${pos.z} minecraft:crafting_table`)
  const block = await waitFor(() => {
    const b = bot.blockAt(pos)
    return b && b.name === 'crafting_table' ? b : null
  }, 5000)
  if (!block) throw new Error('crafting table did not appear')
  await bot.lookAt(pos.offset(0.5, 0.5, 0.5), true)
  return bot.openBlock(block)
}

function findSlot (window, predicate) {
  for (let slot = window.inventoryStart; slot < window.inventoryEnd; slot++) {
    if (predicate(window.slots[slot])) return slot
  }
  return null
}

// Pick up a whole stack, right-click `perSlot` items into each slot, put the rest back.
async function place (window, predicate, slots, perSlot) {
  const source = findSlot(window, predicate)
  if (source === null) throw new Error('item to place is missing from the inventory')
  await bot.clickWindow(source, 0, 0)
  for (const slot of slots) {
    for (let i = 0; i < perSlot; i++) await bot.clickWindow(slot, 1, 0)
  }
  if (window.selectedItem) await bot.clickWindow(source, 0, 0)
}

async function takeResult (window, shift) {
  if (shift) {
    await bot.clickWindow(RESULT, 0, 1)
  } else {
    await bot.clickWindow(RESULT, 0, 0)
    await bot.clickWindow(window.firstEmptyInventorySlot(), 0, 0)
  }
  await sleep(500)
}

async function setUp (items) {
  bot.chat(`/clear ${username}`)
  await waitFor(() => bot.inventory.items().length === 0, 5000)
  for (const [name, count] of items) await give(name, count)
  return openCraftingTable()
}

function itemKey (item) {
  return legacy() ? `${item.name}@${item.metadata}` : item.name
}

const key = {
  enchanted: () => legacy() ? 'golden_apple@1' : 'enchanted_golden_apple',
  golden: () => legacy() ? 'golden_apple@0' : 'golden_apple',
  plain: name => legacy() ? `${name}@0` : name
}

// Closing the table returns the grid to the inventory, so the inventory after
// closing shows what the server really consumed, even when the client view is stale.
async function finish (window, checks, expected) {
  const grid = describe(window, [RESULT, ...GRID])
  bot.closeWindow(window)
  await sleep(1500)
  const inventory = {}
  for (const item of bot.inventory.items()) inventory[itemKey(item)] = (inventory[itemKey(item)] || 0) + item.count
  const inventoryOk = JSON.stringify(Object.entries(inventory).sort()) === JSON.stringify(Object.entries(expected).sort())
  return { ok: inventoryOk && Object.values(checks).every(Boolean), ...checks, inventoryOk, inventory, expected, grid }
}

const scenarios = {
  // Craftable Notch Apples: 8 gold blocks around an apple.
  async datapack () {
    const window = await setUp([['gold_block', 8], ['apple', 1]])
    await place(window, i => i && i.name === 'gold_block', OUTER, 1)
    await place(window, i => i && i.name === 'apple', [CENTER], 1)
    const shown = await waitFor(() => isEnchantedApple(window.slots[RESULT]), 3000)
    if (!shown) return finish(window, { resultShown: false }, {})
    await takeResult(window, false)
    return finish(window, { resultShown: true }, { [key.enchanted()]: 1 })
  },

  // Upgradable Gaps: 8 ingots in each outer slot around a golden apple.
  async upgrade () {
    const window = await setUp([['gold_ingot', 64], ['golden_apple', 1]])
    await place(window, i => i && i.name === 'gold_ingot', OUTER, 8)
    await place(window, isGoldenApple, [CENTER], 1)
    const shown = await waitFor(() => isEnchantedApple(window.slots[RESULT]), 3000)
    if (!shown) return finish(window, { resultShown: false }, {})
    await takeResult(window, false)
    return finish(window, { resultShown: true }, { [key.enchanted()]: 1 })
  },

  // Shift-click crafts one per golden apple and eats 8 ingots per slot each time.
  async upgradeBatch () {
    const window = await setUp([['gold_ingot', 64], ['gold_ingot', 64], ['golden_apple', 2]])
    await place(window, i => i && i.name === 'gold_ingot' && i.count === 64, OUTER.slice(0, 4), 16)
    await place(window, i => i && i.name === 'gold_ingot' && i.count === 64, OUTER.slice(4), 16)
    await place(window, isGoldenApple, [CENTER], 2)
    const shown = await waitFor(() => isEnchantedApple(window.slots[RESULT]), 3000)
    if (!shown) return finish(window, { resultShown: false }, {})
    await takeResult(window, true)
    return finish(window, { resultShown: true }, { [key.enchanted()]: 2 })
  },

  // One slot short: no result, and nothing may be consumed.
  async upgradeShort () {
    const window = await setUp([['gold_ingot', 63], ['golden_apple', 1]])
    await place(window, i => i && i.name === 'gold_ingot', OUTER.slice(0, 7), 8)
    await place(window, i => i && i.name === 'gold_ingot', [OUTER[7]], 7)
    await place(window, isGoldenApple, [CENTER], 1)
    await sleep(1500)
    return finish(window, { noResult: !window.slots[RESULT] }, { [key.plain('gold_ingot')]: 63, [key.golden()]: 1 })
  },

  // The vanilla golden apple recipe must keep working next to the upgrade.
  async vanillaGoldenApple () {
    const window = await setUp([['gold_ingot', 8], ['apple', 1]])
    await place(window, i => i && i.name === 'gold_ingot', OUTER, 1)
    await place(window, i => i && i.name === 'apple', [CENTER], 1)
    const shown = await waitFor(() => isGoldenApple(window.slots[RESULT]), 3000)
    if (!shown) return finish(window, { resultShown: false }, {})
    await takeResult(window, false)
    return finish(window, { resultShown: true }, { [key.golden()]: 1 })
  }
}

const watchdog = setTimeout(() => {
  report({ ok: false, error: 'bot timed out' })
  process.exit(1)
}, 100000)

bot.once('spawn', async () => {
  let result
  try {
    await sleep(1500)
    if (!scenarios[scenario]) throw new Error(`unknown scenario ${scenario}`)
    result = await scenarios[scenario]()
  } catch (err) {
    result = { ok: false, error: String((err && err.stack) || err) }
  }
  clearTimeout(watchdog)
  report(result)
  bot.quit()
  setTimeout(() => process.exit(0), 500)
})

bot.on('kicked', reason => {
  report({ ok: false, error: 'kicked: ' + JSON.stringify(reason) })
  process.exit(1)
})

bot.on('error', err => {
  report({ ok: false, error: 'connection error: ' + String(err) })
  process.exit(1)
})
