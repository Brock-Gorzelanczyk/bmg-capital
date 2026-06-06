/**
 * Unified indicator surface — wraps talib.js (WASM, ~150 indicators) with
 * a graceful fallback to @ixjb94/indicators (pure TS) for environments
 * where WASM isn't available yet.
 *
 * Usage:
 *   import { RSI, MACD, BBANDS, CDLHAMMER } from '@/lib/indicators'
 *   const rsi = await RSI(closes, 14)
 */

// ── talib.js lazy init ────────────────────────────────────────────────────────
import type { TALib as TALibType } from "talib.js";

let _TALib: typeof TALibType | null = null;
let _init: Promise<typeof TALibType> | null = null;

async function getTA(): Promise<typeof TALibType> {
  if (_TALib) return _TALib;
  if (!_init) {
    _init = import("talib.js").then((m) => {
      _TALib = m.TALib;
      return _TALib;
    });
  }
  return _init;
}

// ── @ixjb94/indicators (pure TS fallback) ───────────────────────────────────
import * as Pure from "@ixjb94/indicators";

// ── Shared types ─────────────────────────────────────────────────────────────
export interface OHLCVBars {
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
}

// ── Overlap Studies ──────────────────────────────────────────────────────────

export async function SMA(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.SMA({ inReal, optInTimePeriod: timePeriod });
    return r.outReal;
  }
  return Pure.SMA.calculate({ period: timePeriod, values: inReal });
}

export async function EMA(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.EMA({ inReal, optInTimePeriod: timePeriod });
    return r.outReal;
  }
  return Pure.EMA.calculate({ period: timePeriod, values: inReal });
}

export async function WMA(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.WMA({ inReal, optInTimePeriod: timePeriod });
    return r.outReal;
  }
  return Pure.WMA.calculate({ period: timePeriod, values: inReal });
}

export async function DEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.DEMA({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function TEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.TEMA({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function TRIMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.TRIMA({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function KAMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.KAMA({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function BBANDS(
  inReal: number[],
  timePeriod = 5,
  nbDevUp = 2,
  nbDevDn = 2,
): Promise<{ upperBand: number[]; middleBand: number[]; lowerBand: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.BBANDS({
      inReal,
      optInTimePeriod: timePeriod,
      optInNbDevUp: nbDevUp,
      optInNbDevDn: nbDevDn,
      optInMAType: 0,
    });
    return {
      upperBand: r.outRealUpperBand,
      middleBand: r.outRealMiddleBand,
      lowerBand: r.outRealLowerBand,
    };
  }
  const result = Pure.BollingerBands.calculate({
    period: timePeriod,
    values: inReal,
    stdDev: nbDevUp,
  });
  return {
    upperBand: result.map((r: any) => r.upper),
    middleBand: result.map((r: any) => r.middle),
    lowerBand: result.map((r: any) => r.lower),
  };
}

export async function SAR(
  high: number[],
  low: number[],
  acceleration = 0.02,
  maximum = 0.2,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.SAR({
    inHigh: high,
    inLow: low,
    optInAcceleration: acceleration,
    optInMaximum: maximum,
  });
  return r.outReal;
}

export async function HT_TRENDLINE(inReal: number[]): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.HT_TRENDLINE({ inReal });
  return r.outReal;
}

// ── Momentum Indicators ──────────────────────────────────────────────────────

export async function RSI(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.RSI({ inReal, optInTimePeriod: timePeriod });
    return r.outReal;
  }
  return Pure.RSI.calculate({ period: timePeriod, values: inReal });
}

export async function MACD(
  inReal: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9,
): Promise<{ macd: number[]; signal: number[]; histogram: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.MACD({
      inReal,
      optInFastPeriod: fastPeriod,
      optInSlowPeriod: slowPeriod,
      optInSignalPeriod: signalPeriod,
    });
    return {
      macd: r.outMACD,
      signal: r.outMACDSignal,
      histogram: r.outMACDHist,
    };
  }
  const result = Pure.MACD.calculate({
    values: inReal,
    fastPeriod,
    slowPeriod,
    signalPeriod,
    SimpleMAOscillator: false,
    SimpleMASignal: false,
  });
  return {
    macd: result.map((r: any) => r.MACD ?? 0),
    signal: result.map((r: any) => r.signal ?? 0),
    histogram: result.map((r: any) => r.histogram ?? 0),
  };
}

export async function STOCH(
  high: number[],
  low: number[],
  close: number[],
  fastKPeriod = 5,
  slowKPeriod = 3,
  slowDPeriod = 3,
): Promise<{ slowK: number[]; slowD: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.STOCH({
      inHigh: high,
      inLow: low,
      inClose: close,
      optInFastKPeriod: fastKPeriod,
      optInSlowKPeriod: slowKPeriod,
      optInSlowKMAType: 0,
      optInSlowDPeriod: slowDPeriod,
      optInSlowDMAType: 0,
    });
    return { slowK: r.outSlowK, slowD: r.outSlowD };
  }
  const result = Pure.Stochastic.calculate({
    high,
    low,
    close,
    period: fastKPeriod,
    signalPeriod: slowDPeriod,
  });
  return {
    slowK: result.map((r: any) => r.k ?? 0),
    slowD: result.map((r: any) => r.d ?? 0),
  };
}

export async function STOCHRSI(
  inReal: number[],
  timePeriod = 14,
  fastKPeriod = 5,
  fastDPeriod = 3,
): Promise<{ fastK: number[]; fastD: number[] }> {
  const ta = await getTA();
  const r = await ta.STOCHRSI({
    inReal,
    optInTimePeriod: timePeriod,
    optInFastKPeriod: fastKPeriod,
    optInFastDPeriod: fastDPeriod,
    optInFastDMAType: 0,
  });
  return { fastK: r.outFastK, fastD: r.outFastD };
}

export async function ADX(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.ADX({
      inHigh: high,
      inLow: low,
      inClose: close,
      optInTimePeriod: timePeriod,
    });
    return r.outReal;
  }
  return Pure.ADX.calculate({ high, low, close, period: timePeriod }).map(
    (r: any) => r.adx,
  );
}

export async function AROON(
  high: number[],
  low: number[],
  timePeriod = 14,
): Promise<{ aroonDown: number[]; aroonUp: number[] }> {
  const ta = await getTA();
  const r = await ta.AROON({ inHigh: high, inLow: low, optInTimePeriod: timePeriod });
  return { aroonDown: r.outAroonDown, aroonUp: r.outAroonUp };
}

export async function AROONOSC(
  high: number[],
  low: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.AROONOSC({ inHigh: high, inLow: low, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function CCI(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.CCI({
      inHigh: high,
      inLow: low,
      inClose: close,
      optInTimePeriod: timePeriod,
    });
    return r.outReal;
  }
  return Pure.CCI.calculate({ high, low, close, period: timePeriod });
}

export async function MOM(inReal: number[], timePeriod = 10): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.MOM({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function ROC(inReal: number[], timePeriod = 10): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.ROC({ inReal, optInTimePeriod: timePeriod });
    return r.outReal;
  }
  return Pure.ROC.calculate({ period: timePeriod, values: inReal });
}

export async function WILLR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.WILLR({
      inHigh: high,
      inLow: low,
      inClose: close,
      optInTimePeriod: timePeriod,
    });
    return r.outReal;
  }
  return Pure.WilliamsR.calculate({ high, low, close, period: timePeriod });
}

export async function ULTOSC(
  high: number[],
  low: number[],
  close: number[],
  timePeriod1 = 7,
  timePeriod2 = 14,
  timePeriod3 = 28,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.ULTOSC({
    inHigh: high,
    inLow: low,
    inClose: close,
    optInTimePeriod1: timePeriod1,
    optInTimePeriod2: timePeriod2,
    optInTimePeriod3: timePeriod3,
  });
  return r.outReal;
}

// ── Volume Indicators ────────────────────────────────────────────────────────

export async function OBV(close: number[], volume: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.OBV({ inReal: close, inVolume: volume });
    return r.outReal;
  }
  return Pure.OBV.calculate({ close, volume });
}

export async function AD(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.AD({ inHigh: high, inLow: low, inClose: close, inVolume: volume });
  return r.outReal;
}

export async function ADOSC(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  fastPeriod = 3,
  slowPeriod = 10,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.ADOSC({
    inHigh: high,
    inLow: low,
    inClose: close,
    inVolume: volume,
    optInFastPeriod: fastPeriod,
    optInSlowPeriod: slowPeriod,
  });
  return r.outReal;
}

export async function MFI(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.MFI({
      inHigh: high,
      inLow: low,
      inClose: close,
      inVolume: volume,
      optInTimePeriod: timePeriod,
    });
    return r.outReal;
  }
  return Pure.MFI.calculate({ high, low, close, volume, period: timePeriod });
}

/** Chaikin Money Flow — not in TA-Lib, implemented in pure TS. */
export function CMF(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  period = 20,
): number[] {
  const results: number[] = [];
  for (let i = period - 1; i < close.length; i++) {
    let mfvSum = 0;
    let volSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const hl = high[j] - low[j];
      const mfm = hl === 0 ? 0 : ((close[j] - low[j]) - (high[j] - close[j])) / hl;
      mfvSum += mfm * volume[j];
      volSum += volume[j];
    }
    results.push(volSum === 0 ? 0 : mfvSum / volSum);
  }
  return results;
}

// ── Volatility Indicators ────────────────────────────────────────────────────

export async function ATR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.ATR({
      inHigh: high,
      inLow: low,
      inClose: close,
      optInTimePeriod: timePeriod,
    });
    return r.outReal;
  }
  return Pure.ATR.calculate({ high, low, close, period: timePeriod });
}

export async function NATR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.NATR({
    inHigh: high,
    inLow: low,
    inClose: close,
    optInTimePeriod: timePeriod,
  });
  return r.outReal;
}

export async function TRANGE(
  high: number[],
  low: number[],
  close: number[],
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.TRANGE({ inHigh: high, inLow: low, inClose: close });
  return r.outReal;
}

// ── Cycle Indicators ─────────────────────────────────────────────────────────

export async function HT_DCPERIOD(inReal: number[]): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.HT_DCPERIOD({ inReal });
  return r.outReal;
}

export async function HT_SINE(
  inReal: number[],
): Promise<{ sine: number[]; leadSine: number[] }> {
  const ta = await getTA();
  const r = await ta.HT_SINE({ inReal });
  return { sine: r.outSine, leadSine: r.outLeadSine };
}

export async function HT_TRENDMODE(inReal: number[]): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.HT_TRENDMODE({ inReal });
  return r.outInteger;
}

// ── Statistic Functions ───────────────────────────────────────────────────────

export async function LINEARREG(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.LINEARREG({ inReal, optInTimePeriod: timePeriod });
  return r.outReal;
}

export async function STDDEV(
  inReal: number[],
  timePeriod = 5,
  nbDev = 1,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.STDDEV({ inReal, optInTimePeriod: timePeriod, optInNbDev: nbDev });
  return r.outReal;
}

export async function VAR(inReal: number[], timePeriod = 5): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.VAR({ inReal, optInTimePeriod: timePeriod, optInNbDev: 1 });
  return r.outReal;
}

// ── Math Transform ───────────────────────────────────────────────────────────

export async function SQRT(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.SQRT({ inReal });
    return r.outReal;
  }
  return inReal.map(Math.sqrt);
}

export async function LN(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta) {
    const r = await ta.LN({ inReal });
    return r.outReal;
  }
  return inReal.map(Math.log);
}

// ── Pattern Recognition ───────────────────────────────────────────────────────
// Returns 100 (bullish), -100 (bearish), 0 (none) per bar.

export async function CDLHAMMER(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLHAMMER({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDLDOJI(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLDOJI({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDLENGULFING(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLENGULFING({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDL3WHITESOLDIERS(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDL3WHITESOLDIERS({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDL3BLACKCROWS(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDL3BLACKCROWS({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDLSHOOTINGSTAR(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLSHOOTINGSTAR({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDLMORNINGSTAR(
  bars: OHLCVBars,
  penetration = 0,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLMORNINGSTAR({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
    optInPenetration: penetration,
  });
  return r.outInteger;
}

export async function CDLEVENINGSTAR(
  bars: OHLCVBars,
  penetration = 0,
): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLEVENINGSTAR({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
    optInPenetration: penetration,
  });
  return r.outInteger;
}

export async function CDLHARAMI(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLHARAMI({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
}

export async function CDLPIERCING(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA();
  const r = await ta.CDLPIERCING({
    inOpen: bars.open,
    inHigh: bars.high,
    inLow: bars.low,
    inClose: bars.close,
  });
  return r.outInteger;
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
