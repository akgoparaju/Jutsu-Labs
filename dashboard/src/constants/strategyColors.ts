/**
 * Strategy Color System - Colorblind-Friendly Color & Pattern Definitions
 *
 * Provides consistent colors and line patterns for multi-strategy comparison views.
 * Designed for accessibility with patterns that distinguish lines even when colors
 * are indistinguishable.
 *
 * @version 1.0.0
 * @part Multi-Strategy Comparison UI
 */

import { LineStyle } from 'lightweight-charts'

/**
 * Strategy style configuration with color and line pattern
 */
export interface StrategyStyle {
  /** Hex color code */
  color: string
  /** Human-readable color name */
  name: string
  /** Tailwind CSS class suffix */
  tailwind: string
  /** lightweight-charts line style */
  lineStyle: typeof LineStyle[keyof typeof LineStyle]
  /** CSS pattern description for legend */
  patternDesc: string
}

/**
 * Array of strategy styles indexed by selection order (0, 1, 2)
 * Colors and patterns are designed to be distinguishable for colorblind users
 */
export const STRATEGY_COLORS: readonly StrategyStyle[] = [
  {
    color: '#3b82f6',
    name: 'Blue',
    tailwind: 'blue-500',
    lineStyle: LineStyle.Solid,
    patternDesc: 'Solid (━━━)',
  },
  {
    color: '#22c55e',
    name: 'Green',
    tailwind: 'green-500',
    lineStyle: LineStyle.Dashed,
    patternDesc: 'Dashed (- - -)',
  },
  {
    color: '#f59e0b',
    name: 'Amber',
    tailwind: 'amber-500',
    lineStyle: LineStyle.Dotted,
    patternDesc: 'Dotted (···)',
  },
] as const

/**
 * Baseline (QQQ) style - always gray with long dash pattern
 */
export const BASELINE_STYLE: Readonly<StrategyStyle> = {
  color: '#9ca3af',
  name: 'Gray',
  tailwind: 'gray-400',
  lineStyle: LineStyle.LargeDashed,
  patternDesc: 'Long Dash (— — —)',
} as const

/**
 * Maximum number of strategies that can be compared simultaneously
 */
export const MAX_COMPARE_STRATEGIES = 3

/**
 * Get strategy style by index (wraps around if index > array length)
 */
export function getStrategyStyle(index: number): StrategyStyle {
  return STRATEGY_COLORS[index % STRATEGY_COLORS.length]
}

/**
 * Get strategy color hex value by index
 */
export function getStrategyColor(index: number): string {
  return getStrategyStyle(index).color
}

/**
 * Get Tailwind CSS background class for strategy chip
 */
export function getStrategyBgClass(index: number): string {
  const style = getStrategyStyle(index)
  return `bg-${style.tailwind}`
}

/**
 * Get Tailwind CSS text class for strategy text
 */
export function getStrategyTextClass(index: number): string {
  const style = getStrategyStyle(index)
  return `text-${style.tailwind}`
}

/**
 * Color definitions for inline styles (Tailwind arbitrary values may not work)
 */
export const STRATEGY_COLOR_HEX = {
  0: '#3b82f6', // Blue
  1: '#22c55e', // Green
  2: '#f59e0b', // Amber
  baseline: '#9ca3af', // Gray
} as const

/**
 * Pattern indicators for use in table headers and legends
 * Shows visual representation of line pattern alongside color
 */
export const PATTERN_INDICATORS = {
  solid: '━',
  dashed: '- -',
  dotted: '···',
  longDash: '— —',
} as const

/**
 * Get pattern indicator string for strategy index
 */
export function getPatternIndicator(index: number): string {
  switch (index) {
    case 0:
      return PATTERN_INDICATORS.solid
    case 1:
      return PATTERN_INDICATORS.dashed
    case 2:
      return PATTERN_INDICATORS.dotted
    default:
      return PATTERN_INDICATORS.solid
  }
}
