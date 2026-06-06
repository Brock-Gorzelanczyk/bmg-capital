/**
 * Unified indicator surface.
 *
 * Primary: talib.js (WASM port of TA-Lib, ~150 indicators).
 *   - Named exports, sync after init(), no optIn* prefix.
 *   - Must await ensureTalib() before calling any function.
 *
 * Fallback: @ixjb94/indicators (pure async TS).
 *   - All lowercase, positional args.
 *
 * Usage:
 *   import { RSI, MACD, BBANDS, CDLHAMMER } from '@/lib/indicators'
 *   const values = await RSI(closes, 14)
 */

// ── talib.js init ─────────────────────────────────────────────────────────────
import { init as talibInit } from "talib.js";
import * as talib from "talib.js";

let _talibReady: Promise<void> | null = null;

function ensureTalib(): Promise<void> {
  if (!_talibReady) _talibReady = talibInit();
  return _talibReady;
}

// ── @ixjb94/indicators ────────────────────────────────────────────────────────
import * as pure from "@ixjb94/indicators";

// ── Shared types ──────────────────────────────────────────────────────────────
export interface OHLCVBars {
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
}

// ── Overlap Studies ───────────────────────────────────────────────────────────

export async function SMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.SMA({ inReal, timePeriod }).output;
  } catch {
    return pure.sma(inReal, timePeriod);
  }
}

export async function EMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.EMA({ inReal, timePeriod }).output;
  } catch {
    return pure.ema(inReal, timePeriod);
  }
}

export async function WMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.WMA({ inReal, timePeriod }).output;
  } catch {
    return pure.wma(inReal, timePeriod);
  }
}

export async function DEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  await ensureTalib();
  return talib.DEMA({ inReal, timePeriod }).output;
}

export async function TEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  await ensureTalib();
  return talib.TEMA({ inReal, timePeriod }).output;
}

export async function TRIMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  await ensureTalib();
  return talib.TRIMA({ inReal, timePeriod }).output;
}

export async function KAMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  await ensureTalib();
  return talib.KAMA({ inReal, timePeriod }).output;
}

export async function BBANDS(
  inReal: number[],
  timePeriod = 5,
  nbDevUp = 2,
  nbDevDn = 2,
): Promise<{ upperBand: number[]; middleBand: number[]; lowerBand: number[] }> {
  try {
    await ensureTalib();
    const r = talib.BBANDS({ inReal, timePeriod, nbDevUp, nbDevDn });
    return { upperBand: r.upperBand, middleBand: r.middleBand, lowerBand: r.lowerBand };
  } catch {
    // @ixjb94 bbands returns [upper[], middle[], lower[]]
    const r = await pure.bbands(inReal, timePeriod, nbDevUp);
    return { upperBand: r[0], middleBand: r[1], lowerBand: r[2] };
  }
}

export async function SAR(
  high: number[],
  low: number[],
  acceleration = 0.02,
  maximum = 0.2,
): Promise<number[]> {
  await ensureTalib();
  return talib.SAR({ high, low, acceleration, maximum }).output;
}

export async function HT_TRENDLINE(inReal: number[]): Promise<number[]> {
  await ensureTalib();
  return talib.HT_TRENDLINE({ inReal }).output;
}

// ── Momentum Indicators ───────────────────────────────────────────────────────

export async function RSI(inReal: number[], timePeriod = 14): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.RSI({ inReal, timePeriod }).output;
  } catch {
    return pure.rsi(inReal, timePeriod);
  }
}

export async function MACD(
  inReal: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9,
): Promise<{ macd: number[]; signal: number[]; histogram: number[] }> {
  try {
    await ensureTalib();
    const r = talib.MACD({ inReal, fastPeriod, slowPeriod, signalPeriod });
    return { macd: r.MACD, signal: r.MACDSignal, histogram: r.MACDHist };
  } catch {
    // @ixjb94 macd returns [macd[], signal[], hist[]]
    const r = await pure.macd(inReal, fastPeriod, slowPeriod, signalPeriod);
    return { macd: r[0], signal: r[1], histogram: r[2] };
  }
}

export async function STOCH(
  high: number[],
  low: number[],
  close: number[],
  fastKPeriod = 5,
  slowKPeriod = 3,
  slowDPeriod = 3,
): Promise<{ slowK: number[]; slowD: number[] }> {
  try {
    await ensureTalib();
    const r = talib.STOCH({
      high, low, close,
      fastK_Period: fastKPeriod,
      slowK_Period: slowKPeriod,
      slowD_Period: slowDPeriod,
    });
    return { slowK: r.slowK, slowD: r.slowD };
  } catch {
    // @ixjb94 stoch returns [k[], d[]]
    const r = await pure.stoch(high, low, close, fastKPeriod, slowKPeriod, slowDPeriod);
    return { slowK: r[0], slowD: r[1] };
  }
}

export async function STOCHRSI(
  inReal: number[],
  timePeriod = 14,
  fastKPeriod = 5,
  fastDPeriod = 3,
): Promise<{ fastK: number[]; fastD: number[] }> {
  await ensureTalib();
  const r = talib.STOCHRSI({ inReal, timePeriod, fastK_Period: fastKPeriod, fastD_Period: fastDPeriod });
  return { fastK: r.fastK, fastD: r.fastD };
}

export async function ADX(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.ADX({ high, low, close, timePeriod }).output;
  } catch {
    // @ixjb94 adx takes (high, low, period) — no close
    return pure.adx(high, low, timePeriod);
  }
}

export async function AROON(
  high: number[],
  low: number[],
  timePeriod = 14,
): Promise<{ aroonDown: number[]; aroonUp: number[] }> {
  await ensureTalib();
  const r = talib.AROON({ high, low, timePeriod });
  return { aroonDown: r.aroonDown, aroonUp: r.aroonUp };
}

export async function AROONOSC(high: number[], low: number[], timePeriod = 14): Promise<number[]> {
  await ensureTalib();
  return talib.AROONOSC({ high, low, timePeriod }).output;
}

export async function CCI(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.CCI({ high, low, close, timePeriod }).output;
  } catch {
    return pure.cci(high, low, close, timePeriod);
  }
}

export async function MOM(inReal: number[], timePeriod = 10): Promise<number[]> {
  await ensureTalib();
  return talib.MOM({ inReal, timePeriod }).output;
}

export async function ROC(inReal: number[], timePeriod = 10): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.ROC({ inReal, timePeriod }).output;
  } catch {
    return pure.roc(inReal, timePeriod);
  }
}

export async function WILLR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.WILLR({ high, low, close, timePeriod }).output;
  } catch {
    return pure.willr(high, low, close, timePeriod);
  }
}

export async function ULTOSC(
  high: number[],
  low: number[],
  close: number[],
  timePeriod1 = 7,
  timePeriod2 = 14,
  timePeriod3 = 28,
): Promise<number[]> {
  await ensureTalib();
  return talib.ULTOSC({ high, low, close, timePeriod1, timePeriod2, timePeriod3 }).output;
}

// ── Volume Indicators ─────────────────────────────────────────────────────────

export async function OBV(inReal: number[], volume: number[]): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.OBV({ inReal, volume }).output;
  } catch {
    return pure.obv(inReal, volume);
  }
}

export async function AD(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
): Promise<number[]> {
  await ensureTalib();
  return talib.AD({ high, low, close, volume }).output;
}

export async function ADOSC(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  fastPeriod = 3,
  slowPeriod = 10,
): Promise<number[]> {
  await ensureTalib();
  return talib.ADOSC({ high, low, close, volume, fastPeriod, slowPeriod }).output;
}

export async function MFI(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  timePeriod = 14,
): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.MFI({ high, low, close, volume, timePeriod }).output;
  } catch {
    return pure.mfi(high, low, close, volume, timePeriod);
  }
}

/** Chaikin Money Flow — available in both libraries. */
export async function CMF(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  period = 20,
): Promise<number[]> {
  return pure.cmf(high, low, close, volume, period);
}

// ── Volatility Indicators ─────────────────────────────────────────────────────

export async function ATR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.ATR({ high, low, close, timePeriod }).output;
  } catch {
    return pure.atr(high, low, close, timePeriod);
  }
}

export async function NATR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  await ensureTalib();
  return talib.NATR({ high, low, close, timePeriod }).output;
}

export async function TRANGE(high: number[], low: number[], close: number[]): Promise<number[]> {
  await ensureTalib();
  return talib.TRANGE({ high, low, close }).output;
}

// ── Cycle Indicators ──────────────────────────────────────────────────────────

export async function HT_DCPERIOD(inReal: number[]): Promise<number[]> {
  await ensureTalib();
  return talib.HT_DCPERIOD({ inReal }).output;
}

export async function HT_SINE(
  inReal: number[],
): Promise<{ sine: number[]; leadSine: number[] }> {
  await ensureTalib();
  const r = talib.HT_SINE({ inReal });
  return { sine: r.sine, leadSine: r.leadSine };
}

export async function HT_TRENDMODE(inReal: number[]): Promise<number[]> {
  await ensureTalib();
  return talib.HT_TRENDMODE({ inReal }).output;
}

// ── Statistic Functions ───────────────────────────────────────────────────────

export async function LINEARREG(inReal: number[], timePeriod = 14): Promise<number[]> {
  await ensureTalib();
  return talib.LINEARREG({ inReal, timePeriod }).output;
}

export async function STDDEV(inReal: number[], timePeriod = 5, nbDev = 1): Promise<number[]> {
  await ensureTalib();
  return talib.STDDEV({ inReal, timePeriod, nbDev }).output;
}

export async function VAR(inReal: number[], timePeriod = 5): Promise<number[]> {
  await ensureTalib();
  return talib.VAR({ inReal, timePeriod, nbDev: 1 }).output;
}

// ── Math Transform ────────────────────────────────────────────────────────────

export async function SQRT(inReal: number[]): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.SQRT({ inReal }).output;
  } catch {
    return inReal.map(Math.sqrt);
  }
}

export async function LN(inReal: number[]): Promise<number[]> {
  try {
    await ensureTalib();
    return talib.LN({ inReal }).output;
  } catch {
    return inReal.map(Math.log);
  }
}

// ── Pattern Recognition ───────────────────────────────────────────────────────
// talib.js pattern functions take { open, high, low, close } and return { output: number[] }
// where output values are 100 (bullish), -100 (bearish), 0 (none).

export async function CDLHAMMER(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLHAMMER({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDLDOJI(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLDOJI({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDLENGULFING(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLENGULFING({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDL3WHITESOLDIERS(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDL3WHITESOLDIERS({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDL3BLACKCROWS(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDL3BLACKCROWS({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDLSHOOTINGSTAR(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLSHOOTINGSTAR({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDLMORNINGSTAR(bars: OHLCVBars, penetration = 0.3): Promise<number[]> {
  await ensureTalib();
  return talib.CDLMORNINGSTAR({
    open: bars.open, high: bars.high, low: bars.low, close: bars.close,
    penetration,
  }).output;
}

export async function CDLEVENINGSTAR(bars: OHLCVBars, penetration = 0.3): Promise<number[]> {
  await ensureTalib();
  return talib.CDLEVENINGSTAR({
    open: bars.open, high: bars.high, low: bars.low, close: bars.close,
    penetration,
  }).output;
}

export async function CDLHARAMI(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLHARAMI({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

export async function CDLPIERCING(bars: OHLCVBars): Promise<number[]> {
  await ensureTalib();
  return talib.CDLPIERCING({ open: bars.open, high: bars.high, low: bars.low, close: bars.close }).output;
}

// ── Convenience combo ─────────────────────────────────────────────────────────

export async function standardOverlays(bars: OHLCVBars): Promise<{
  rsi: number[];
  macd: Awaited<ReturnType<typeof MACD>>;
  bbands: Awaited<ReturnType<typeof BBANDS>>;
  atr: number[];
}> {
  const [rsi, macd, bbands, atr] = await Promise.all([
    RSI(bars.close),
    MACD(bars.close),
    BBANDS(bars.close),
    ATR(bars.high, bars.low, bars.close),
  ]);
  return { rsi, macd, bbands, atr };
}
