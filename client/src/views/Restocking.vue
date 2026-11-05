<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="step"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ t('restocking.budgetMax', { amount: formatMoney(maxBudget) }) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.selectedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(selectedTotal) }}</div>
        </div>
        <div :class="['stat-card', remaining < 0 ? 'danger' : 'success']">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remaining) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.selectedItems') }}</div>
          <div class="stat-value">{{ selectedRows.length }} / {{ rows.length }}</div>
        </div>
      </div>

      <div v-if="orderResult" class="confirmation" role="status">
        <strong>{{ t('restocking.orderPlaced') }}</strong>
        <span>{{ t('restocking.orderNumber', { number: orderResult.order_number }) }}</span>
        <span>{{ t('restocking.expectedDelivery', { date: formatDate(orderResult.expected_delivery) }) }}</span>
        <span>{{ t('restocking.leadTimeLine', { days: orderResult.lead_time_days }) }}</span>
        <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="submit-error" role="alert">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ rows.length }})</h3>
          <div class="order-actions">
            <span v-if="overBudget" class="over-budget">{{ t('restocking.overBudget') }}</span>
            <button class="place-order" :disabled="!canPlaceOrder" @click="placeOrder">
              {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
            </button>
          </div>
        </div>

        <div v-if="rows.length === 0" class="empty-state">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table class="restocking-table">
            <thead>
              <tr>
                <th class="col-check">{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.supplier') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="col-num">{{ t('restocking.table.quantity') }}</th>
                <th class="col-num">{{ t('restocking.table.unitCost') }}</th>
                <th class="col-num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="col-num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.sku" :class="{ deselected: !row.selected }">
                <td class="col-check">
                  <input
                    type="checkbox"
                    :checked="row.selected"
                    :aria-label="translateProductName(row.name)"
                    @change="setSelected(row.sku, $event.target.checked)"
                  />
                </td>
                <td>
                  <strong>{{ translateProductName(row.name) }}</strong>
                  <div class="sku">{{ row.sku }}</div>
                </td>
                <td>{{ row.supplier }}</td>
                <td>
                  <span :class="['badge', row.trend]">{{ t(`trends.${row.trend}`) }}</span>
                </td>
                <td class="col-num">
                  <input
                    class="qty-input"
                    type="number"
                    min="1"
                    :max="MAX_QUANTITY"
                    step="1"
                    :value="row.quantity"
                    @change="setQuantity(row.sku, $event.target, row.quantity)"
                  />
                </td>
                <td class="col-num">{{ formatUnitCost(row.unitCost) }}</td>
                <td class="col-num"><strong>{{ formatMoney(row.lineTotal) }}</strong></td>
                <td class="col-num">{{ t('restocking.days', { count: row.leadTime }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()

    // Matches the server-side per-line limit (le=100000)
    const MAX_QUANTITY = 100000

    // Work in integer cents for all budget comparisons to avoid float drift
    const toCents = (amount) => Math.round(amount * 100)

    const currencySymbol = computed(() => (currentCurrency.value === 'JPY' ? '¥' : '$'))

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    // User edits keyed by sku: { selected?: boolean, quantity?: number }
    // quantity is present only when the user explicitly edited it

    const edits = ref({})
    const submitting = ref(false)
    const submitError = ref(null)
    const orderResult = ref(null)

    const gapOf = (f) => f.forecasted_demand - f.current_demand

    // Only items with a positive demand gap need restocking
    const gapItems = computed(() => forecasts.value.filter(f => gapOf(f) > 0))

    // Budget needed to cover every positive gap in full
    const maxBudget = computed(() =>
      Math.ceil(gapItems.value.reduce((sum, f) => sum + gapOf(f) * f.unit_cost, 0))
    )

    // Slider granularity scales with the range
    const step = computed(() => {
      if (maxBudget.value >= 100000) return 1000
      if (maxBudget.value >= 10000) return 100
      return 10
    })

    // Rank: 'increasing' trend first, then by gap descending
    const ranked = computed(() =>
      [...gapItems.value].sort((a, b) => {
        const ai = a.trend === 'increasing' ? 0 : 1
        const bi = b.trend === 'increasing' ? 0 : 1
        if (ai !== bi) return ai - bi
        return gapOf(b) - gapOf(a)
      })
    )

    // Greedy allocation in ranked order: take the full gap while it fits; the first
    // item that does not fit gets floor(remaining / unit_cost) units (skipped if zero).
    // Later cheaper items may still fit with what is left.
    const recommendation = computed(() => {
      let remaining = toCents(budget.value)
      const result = []
      for (const f of ranked.value) {
        if (!(f.unit_cost > 0)) continue
        const gap = gapOf(f)
        const costCents = toCents(f.unit_cost)
        if (costCents <= 0) continue
        const quantity = gap * costCents <= remaining ? gap : Math.floor(remaining / costCents)
        if (quantity <= 0) continue
        remaining -= quantity * costCents
        result.push({ forecast: f, quantity })
      }
      return result
    })

    // Recommendation merged with the user's edits
    const rows = computed(() =>
      recommendation.value.map(({ forecast: f, quantity }) => {
        const edit = edits.value[f.item_sku] || {}
        const qty = edit.quantity ?? quantity
        return {
          sku: f.item_sku,
          name: f.item_name,
          supplier: f.supplier,
          trend: f.trend,
          unitCost: f.unit_cost,
          leadTime: f.lead_time_days,
          quantity: qty,
          selected: edit.selected ?? true,
          lineTotal: (qty * toCents(f.unit_cost)) / 100
        }
      })
    )

    const selectedRows = computed(() => rows.value.filter(r => r.selected && r.quantity > 0))
    const selectedTotalCents = computed(() =>
      selectedRows.value.reduce((s, r) => s + r.quantity * toCents(r.unitCost), 0)
    )
    const selectedTotal = computed(() => selectedTotalCents.value / 100)
    const remaining = computed(() => (toCents(budget.value) - selectedTotalCents.value) / 100)
    const overBudget = computed(() => selectedTotalCents.value > toCents(budget.value))
    const orderLeadTime = computed(() =>
      selectedRows.value.reduce((max, r) => Math.max(max, r.leadTime), 0)
    )
    const canPlaceOrder = computed(
      () => selectedRows.value.length > 0 && !overBudget.value && !submitting.value
    )

    // Edits persist across slider moves, per SKU. Deselections are kept. A user-edited
    // quantity is kept only while the SKU is still recommended; unedited quantities
    // always follow the new recommendation (they are not stored in edits).
    watch(budget, () => {
      const recommended = new Set(recommendation.value.map(r => r.forecast.item_sku))
      const next = {}
      for (const [sku, edit] of Object.entries(edits.value)) {
        const { quantity, ...rest } = edit
        next[sku] = recommended.has(sku) && quantity !== undefined ? edit : rest
      }
      edits.value = next
    })

    const setSelected = (sku, selected) => {
      edits.value = { ...edits.value, [sku]: { ...edits.value[sku], selected } }
    }

    // Invalid input (empty/0/negative) is rejected and the box is reset to the current
    // quantity; values above the max are clamped. The box is one-way bound, so it must
    // be written back manually whenever the model does not take the typed value.
    const setQuantity = (sku, el, current) => {
      let n = Math.floor(Number(el.value))
      if (!Number.isFinite(n) || n < 1) {
        el.value = current
        return
      }
      n = Math.min(n, MAX_QUANTITY)
      el.value = n
      edits.value = { ...edits.value, [sku]: { ...edits.value[sku], quantity: n } }
    }

    const formatMoney = (value) =>
      currencySymbol.value + Math.round(value).toLocaleString()

    // Unit costs keep cents: rounding $42.50 to $43 makes qty x price visibly disagree with the line total
    const formatUnitCost = (value) =>
      currencySymbol.value + value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

    const formatDate = (dateString) => {
      const d = new Date(dateString)
      if (isNaN(d.getTime())) return dateString
      return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Default to roughly half of the maximum, aligned to the slider step
        budget.value = Math.round((maxBudget.value * 0.5) / step.value) * step.value
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (!canPlaceOrder.value) return
      submitting.value = true
      submitError.value = null
      orderResult.value = null
      try {
        const payload = { items: selectedRows.value.map(r => ({ sku: r.sku, quantity: r.quantity })) }
        orderResult.value = await api.createRestockingOrder(payload)
        // Deselect the ordered SKUs so a slider move cannot silently re-select them
        const next = { ...edits.value }
        selectedRows.value.forEach(r => { next[r.sku] = { ...next[r.sku], selected: false } })
        edits.value = next
      } catch (err) {
        // Server may return a non-string detail (e.g. validation error list)
        const detail = err.response?.data?.detail
        submitError.value = typeof detail === 'string' ? detail : t('restocking.submitFailed')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      translateProductName,
      MAX_QUANTITY,
      loading,
      error,
      budget,
      maxBudget,
      step,
      rows,
      selectedRows,
      selectedTotal,
      remaining,
      overBudget,
      orderLeadTime,
      canPlaceOrder,
      submitting,
      submitError,
      orderResult,
      setSelected,
      setQuantity,
      formatMoney,
      formatUnitCost,
      formatDate,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-weight: 600;
  color: #0f172a;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #0f172a;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.confirmation {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 1rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  color: #166534;
  font-size: 0.875rem;
}

.confirmation-link {
  margin-left: auto;
  color: #2563eb;
  font-weight: 500;
}

.submit-error {
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

.order-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.over-budget {
  color: #b91c1c;
  font-size: 0.813rem;
}

.place-order {
  padding: 0.5rem 1.25rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.place-order:hover:not(:disabled) {
  background: #1e293b;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.restocking-table {
  width: 100%;
}

.col-check {
  width: 64px;
  text-align: center;
}

.col-num {
  text-align: right;
}

.sku {
  font-size: 0.813rem;
  color: #64748b;
}

.deselected {
  opacity: 0.55;
}

.qty-input {
  width: 80px;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  text-align: right;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}
</style>
