/**
 * Unified indicator surface — wraps talib.js (WASM, ~150 indicators) with
 * a graceful fallback to @ixjb94/indicators (pure TS) for environments
 * where WASM isn't available yet.
 *
 * Usage:
 *   import { RSI, MACD, BBANDS, CDLHAMMER } from '@/lib/indicators'
 *   const result = await RSI({ inReal: closes, timePeriod: 14 })
 */

// ── talib.js (WASM) ──────────────────────────────────────────────────────────
// talib.js is async-initialized; we lazily load it to avoid blocking the app.
let _talib: any = null;
let _talibReady: Promise<any> | null = null;

async function getTA(): Promise<any> {
  if (_talib) return _talib;
  if (!_talibReady) {
    _talibReady = import("talib.js").then((m) => {
      _talib = m.default ?? m;
      return _talib;
    });
  }
  return _talibReady;
}

// ── @ixjb94/indicators (pure TS fallback) ───────────────────────────────────
import * as PureIndicators from "@ixjb94/indicators";

// ── Shared input types ───────────────────────────────────────────────────────
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
  if (ta?.SMA) return ta.SMA({ inReal, timePeriod });
  return PureIndicators.SMA.calculate({ period: timePeriod, values: inReal });
}

export async function EMA(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.EMA) return ta.EMA({ inReal, timePeriod });
  return PureIndicators.EMA.calculate({ period: timePeriod, values: inReal });
}

export async function WMA(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.WMA) return ta.WMA({ inReal, timePeriod });
  return PureIndicators.WMA.calculate({ period: timePeriod, values: inReal });
}

export async function DEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.DEMA) return ta.DEMA({ inReal, timePeriod });
  throw new Error("DEMA not available without talib.js WASM");
}

export async function TEMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.TEMA) return ta.TEMA({ inReal, timePeriod });
  throw new Error("TEMA not available without talib.js WASM");
}

export async function TRIMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.TRIMA) return ta.TRIMA({ inReal, timePeriod });
  throw new Error("TRIMA not available without talib.js WASM");
}

export async function KAMA(inReal: number[], timePeriod = 30): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.KAMA) return ta.KAMA({ inReal, timePeriod });
  throw new Error("KAMA not available without talib.js WASM");
}

export async function BBANDS(
  inReal: number[],
  timePeriod = 5,
  nbDevUp = 2,
  nbDevDn = 2,
): Promise<{ upperBand: number[]; middleBand: number[]; lowerBand: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta?.BBANDS)
    return ta.BBANDS({ inReal, timePeriod, nbDevUp, nbDevDn, MAType: 0 });
  const result = PureIndicators.BollingerBands.calculate({
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
  const ta = await getTA().catch(() => null);
  if (ta?.SAR) return ta.SAR({ inHigh: high, inLow: low, acceleration, maximum });
  throw new Error("SAR not available without talib.js WASM");
}

export async function HT_TRENDLINE(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.HT_TRENDLINE) return ta.HT_TRENDLINE({ inReal });
  throw new Error("HT_TRENDLINE not available without talib.js WASM");
}

// ── Momentum Indicators ──────────────────────────────────────────────────────

export async function RSI(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.RSI) return ta.RSI({ inReal, timePeriod });
  return PureIndicators.RSI.calculate({ period: timePeriod, values: inReal });
}

export async function MACD(
  inReal: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9,
): Promise<{ macd: number[]; signal: number[]; histogram: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta?.MACD)
    return ta.MACD({ inReal, fastPeriod, slowPeriod, signalPeriod });
  const result = PureIndicators.MACD.calculate({
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
  if (ta?.STOCH)
    return ta.STOCH({
      inHigh: high, inLow: low, inClose: close,
      fastKPeriod, slowKPeriod, slowKMAType: 0, slowDPeriod, slowDMAType: 0,
    });
  const result = PureIndicators.Stochastic.calculate({
    high, low, close,
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
  const ta = await getTA().catch(() => null);
  if (ta?.STOCHRSI)
    return ta.STOCHRSI({
      inReal, timePeriod, fastKPeriod, fastDPeriod, fastDMAType: 0,
    });
  throw new Error("STOCHRSI not available without talib.js WASM");
}

export async function ADX(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.ADX)
    return ta.ADX({ inHigh: high, inLow: low, inClose: close, timePeriod });
  return PureIndicators.ADX.calculate({ high, low, close, period: timePeriod }).map(
    (r: any) => r.adx,
  );
}

export async function AROON(
  high: number[],
  low: number[],
  timePeriod = 14,
): Promise<{ aroonDown: number[]; aroonUp: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta?.AROON) return ta.AROON({ inHigh: high, inLow: low, timePeriod });
  throw new Error("AROON not available without talib.js WASM");
}

export async function AROONOSC(
  high: number[],
  low: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.AROONOSC) return ta.AROONOSC({ inHigh: high, inLow: low, timePeriod });
  throw new Error("AROONOSC not available without talib.js WASM");
}

export async function CCI(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CCI)
    return ta.CCI({ inHigh: high, inLow: low, inClose: close, timePeriod });
  return PureIndicators.CCI.calculate({ high, low, close, period: timePeriod });
}

export async function MOM(inReal: number[], timePeriod = 10): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.MOM) return ta.MOM({ inReal, timePeriod });
  throw new Error("MOM not available without talib.js WASM");
}

export async function ROC(inReal: number[], timePeriod = 10): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.ROC) return ta.ROC({ inReal, timePeriod });
  return PureIndicators.ROC.calculate({ period: timePeriod, values: inReal });
}

export async function WILLR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.WILLR)
    return ta.WILLR({ inHigh: high, inLow: low, inClose: close, timePeriod });
  return PureIndicators.WilliamsR.calculate({ high, low, close, period: timePeriod });
}

export async function ULTOSC(
  high: number[],
  low: number[],
  close: number[],
  timePeriod1 = 7,
  timePeriod2 = 14,
  timePeriod3 = 28,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.ULTOSC)
    return ta.ULTOSC({
      inHigh: high, inLow: low, inClose: close,
      timePeriod1, timePeriod2, timePeriod3,
    });
  throw new Error("ULTOSC not available without talib.js WASM");
}

// ── Volume Indicators ────────────────────────────────────────────────────────

export async function OBV(close: number[], volume: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.OBV) return ta.OBV({ inReal: close, inVolume: volume });
  return PureIndicators.OBV.calculate({ close, volume });
}

export async function AD(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.AD)
    return ta.AD({ inHigh: high, inLow: low, inClose: close, inVolume: volume });
  throw new Error("AD not available without talib.js WASM");
}

export async function ADOSC(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  fastPeriod = 3,
  slowPeriod = 10,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.ADOSC)
    return ta.ADOSC({
      inHigh: high, inLow: low, inClose: close, inVolume: volume,
      fastPeriod, slowPeriod,
    });
  throw new Error("ADOSC not available without talib.js WASM");
}

export async function MFI(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.MFI)
    return ta.MFI({ inHigh: high, inLow: low, inClose: close, inVolume: volume, timePeriod });
  return PureIndicators.MFI.calculate({ high, low, close, volume, period: timePeriod });
}

// Chaikin Money Flow — composite: AD oscillator normalized by volume
export async function CMF(
  high: number[],
  low: number[],
  close: number[],
  volume: number[],
  period = 20,
): Promise<number[]> {
  // Pure implementation — talib doesn't have CMF directly
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
  if (ta?.ATR)
    return ta.ATR({ inHigh: high, inLow: low, inClose: close, timePeriod });
  return PureIndicators.ATR.calculate({ high, low, close, period: timePeriod });
}

export async function NATR(
  high: number[],
  low: number[],
  close: number[],
  timePeriod = 14,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.NATR)
    return ta.NATR({ inHigh: high, inLow: low, inClose: close, timePeriod });
  throw new Error("NATR not available without talib.js WASM");
}

export async function TRANGE(
  high: number[],
  low: number[],
  close: number[],
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.TRANGE)
    return ta.TRANGE({ inHigh: high, inLow: low, inClose: close });
  throw new Error("TRANGE not available without talib.js WASM");
}

// ── Cycle Indicators ─────────────────────────────────────────────────────────

export async function HT_DCPERIOD(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.HT_DCPERIOD) return ta.HT_DCPERIOD({ inReal });
  throw new Error("HT_DCPERIOD not available without talib.js WASM");
}

export async function HT_SINE(
  inReal: number[],
): Promise<{ sine: number[]; leadSine: number[] }> {
  const ta = await getTA().catch(() => null);
  if (ta?.HT_SINE) return ta.HT_SINE({ inReal });
  throw new Error("HT_SINE not available without talib.js WASM");
}

export async function HT_TRENDMODE(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.HT_TRENDMODE) return ta.HT_TRENDMODE({ inReal });
  throw new Error("HT_TRENDMODE not available without talib.js WASM");
}

// ── Statistic Functions ───────────────────────────────────────────────────────

export async function LINEARREG(inReal: number[], timePeriod = 14): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.LINEARREG) return ta.LINEARREG({ inReal, timePeriod });
  throw new Error("LINEARREG not available without talib.js WASM");
}

export async function STDDEV(
  inReal: number[],
  timePeriod = 5,
  nbDev = 1,
): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.STDDEV) return ta.STDDEV({ inReal, timePeriod, nbDev });
  throw new Error("STDDEV not available without talib.js WASM");
}

export async function VAR(inReal: number[], timePeriod = 5): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.VAR) return ta.VAR({ inReal, timePeriod, nbDev: 1 });
  throw new Error("VAR not available without talib.js WASM");
}

// ── Math Transform ───────────────────────────────────────────────────────────

export async function SQRT(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.SQRT) return ta.SQRT({ inReal });
  return inReal.map(Math.sqrt);
}

export async function LN(inReal: number[]): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.LN) return ta.LN({ inReal });
  return inReal.map(Math.log);
}

// ── Pattern Recognition ───────────────────────────────────────────────────────
// Return 100 (bullish), -100 (bearish), 0 (none) for each bar.

export async function CDLHAMMER(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLHAMMER)
    return ta.CDLHAMMER({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLHAMMER not available without talib.js WASM");
}

export async function CDLDOJI(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLDOJI)
    return ta.CDLDOJI({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLDOJI not available without talib.js WASM");
}

export async function CDLENGULFING(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLENGULFING)
    return ta.CDLENGULFING({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLENGULFING not available without talib.js WASM");
}

export async function CDL3WHITESOLDIERS(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDL3WHITESOLDIERS)
    return ta.CDL3WHITESOLDIERS({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDL3WHITESOLDIERS not available without talib.js WASM");
}

export async function CDL3BLACKCROWS(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDL3BLACKCROWS)
    return ta.CDL3BLACKCROWS({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDL3BLACKCROWS not available without talib.js WASM");
}

export async function CDLSHOOTINGSTAR(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLSHOOTINGSTAR)
    return ta.CDLSHOOTINGSTAR({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLSHOOTINGSTAR not available without talib.js WASM");
}

export async function CDLMORNINGSTAR(bars: OHLCVBars, penetration = 0): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLMORNINGSTAR)
    return ta.CDLMORNINGSTAR({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
      optInPenetration: penetration,
    });
  throw new Error("CDLMORNINGSTAR not available without talib.js WASM");
}

export async function CDLEVENINGSTAR(bars: OHLCVBars, penetration = 0): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLEVENINGSTAR)
    return ta.CDLEVENINGSTAR({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
      optInPenetration: penetration,
    });
  throw new Error("CDLEVENINGSTAR not available without talib.js WASM");
}

export async function CDLHARAMI(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLHARAMI)
    return ta.CDLHARAMI({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLHARAMI not available without talib.js WASM");
}

export async function CDLPIERCING(bars: OHLCVBars): Promise<number[]> {
  const ta = await getTA().catch(() => null);
  if (ta?.CDLPIERCING)
    return ta.CDLPIERCING({
      inOpen: bars.open, inHigh: bars.high, inLow: bars.low, inClose: bars.close,
    });
  throw new Error("CDLPIERCING not available without talib.js WASM");
}

// ── Convenience re-exports for common combos ─────────────────────────────────

/** Compute RSI + MACD + BBANDS in one call (common chart overlay set). */
export async function standardOverlays(
  bars: OHLCVBars,
): Promise<{
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
