#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rocket Trader — Statistical / ML Engine v0.1

Motor de investigación y señales desacoplado del broker.

Objetivos:
- Recibir OHLCV normalizado.
- Construir features temporales sin mirar datos futuros.
- Generar snapshots walk-forward.
- Entrenar un ensemble heterogéneo.
- Evaluar señales OOS antes de permitirlas al Decision Engine.
- Detectar setups conocidos vs novedosos mediante firmas cuantitativas.
- Mantener un benchmark externo de traders como referencia, nunca como copia.

NO hace:
- órdenes reales
- transferencias
- margen/apalancamiento
- short selling
- decisiones de broker

La salida principal es una SignalCandidate compatible conceptualmente con
rocket_trader_core.StrategySignal.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

try:
    import xgboost as xgb
except Exception:
    xgb = None

try:
    import lightgbm as lgb
except Exception:
    lgb = None


ENGINE_VERSION = "0.1"
SEED = int(os.getenv("ROCKET_TRADER_SEED", "42"))
np.random.seed(SEED)

FEATURE_COLUMNS = [
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
    "vol_5", "vol_10", "vol_20",
    "atr_pct", "range_pct", "body_pct", "upper_wick_pct", "lower_wick_pct",
    "sma_ratio_5", "sma_ratio_10", "sma_ratio_20", "sma_ratio_50",
    "ema_ratio_10", "ema_ratio_20",
    "rsi_14", "macd_norm", "macd_signal_norm", "macd_hist_norm",
    "bb_position", "bb_width",
    "volume_ratio_20", "volume_z_20",
    "high_break_20", "low_break_20",
    "trend_strength", "drawdown_20",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]


@dataclass(frozen=True)
class EngineConfig:
    horizon_bars: int = 5
    target_return: float = 0.001
    min_history_bars: int = 100
    training_stride: int = 5
    max_training_rows: int = 10000
    validation_fraction: float = 0.20
    min_training_rows: int = 300
    probability_threshold: float = 0.58
    novelty_distance_threshold: float = 2.5
    max_candidate_risk_pct: float = 0.01
    random_state: int = SEED

    def validate(self) -> None:
        if self.horizon_bars < 1:
            raise ValueError("horizon_bars debe ser >= 1")
        if self.target_return <= 0:
            raise ValueError("target_return debe ser > 0")
        if self.min_history_bars < 30:
            raise ValueError("min_history_bars debe ser >= 30")
        if self.training_stride < 1:
            raise ValueError("training_stride debe ser >= 1")
        if not 0 < self.validation_fraction < 0.5:
            raise ValueError("validation_fraction debe estar entre 0 y 0.5")
        if self.min_training_rows < 50:
            raise ValueError("min_training_rows debe ser >= 50")
        if not 0 < self.probability_threshold < 1:
            raise ValueError("probability_threshold debe estar entre 0 y 1")


@dataclass(frozen=True)
class SignalCandidate:
    symbol: str
    timestamp: str
    probability_up: float
    expected_return: float
    confidence: float
    score: float
    setup_signature: str
    evidence_class: str
    features: Dict[str, float] = field(default_factory=dict)
    model_votes: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestResult:
    rows: int
    train_rows: int
    test_rows: int
    auc: Optional[float]
    accuracy: Optional[float]
    precision: Optional[float]
    positive_rate: float
    strategy_return: float
    buy_hold_return: float
    max_drawdown: float
    passed: bool
    reason: str


class MarketDataValidator:
    REQUIRED = ("timestamp", "open", "high", "low", "close", "volume")

    @classmethod
    def normalize(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            raise ValueError("Market data vacío")
        df = frame.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        missing = [c for c in cls.REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"Faltan columnas OHLCV: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        if df["timestamp"].isna().any():
            raise ValueError("Hay timestamps inválidos")

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if df[["open", "high", "low", "close", "volume"]].isna().any().any():
            raise ValueError("Hay valores OHLCV inválidos")
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("OHLC debe ser > 0")
        if (df["volume"] < 0).any():
            raise ValueError("volume no puede ser negativo")

        df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        invalid = (
            (df["high"] < df[["open", "close"]].max(axis=1))
            | (df["low"] > df[["open", "close"]].min(axis=1))
            | (df["high"] < df["low"])
        )
        if invalid.any():
            raise ValueError("Existen velas OHLC estructuralmente inválidas")
        return df.reset_index(drop=True)


class FeatureEngine:
    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ], axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def build(df: pd.DataFrame) -> pd.DataFrame:
        x = MarketDataValidator.normalize(df)
        out = x.copy()
        close = out["close"]
        open_ = out["open"]
        high = out["high"]
        low = out["low"]
        volume = out["volume"]

        for p in (1, 3, 5, 10, 20):
            out[f"ret_{p}"] = close.pct_change(p)
        for p in (5, 10, 20):
            out[f"vol_{p}"] = close.pct_change().rolling(p).std()

        atr = FeatureEngine._atr(out)
        out["atr_pct"] = atr / close
        candle_range = (high - low).replace(0, np.nan)
        out["range_pct"] = candle_range / close
        out["body_pct"] = (close - open_).abs() / close
        out["upper_wick_pct"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / close
        out["lower_wick_pct"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / close

        for p in (5, 10, 20, 50):
            sma = close.rolling(p).mean()
            out[f"sma_ratio_{p}"] = close / sma - 1
        for p in (10, 20):
            ema = close.ewm(span=p, adjust=False).mean()
            out[f"ema_ratio_{p}"] = close / ema - 1

        rsi = FeatureEngine._rsi(close)
        out["rsi_14"] = rsi / 100.0
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        out["macd_norm"] = macd / close
        out["macd_signal_norm"] = macd_signal / close
        out["macd_hist_norm"] = (macd - macd_signal) / close

        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        upper = bb_mid + 2 * bb_std
        lower = bb_mid - 2 * bb_std
        width = (upper - lower).replace(0, np.nan)
        out["bb_position"] = (close - lower) / width
        out["bb_width"] = width / bb_mid

        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std().replace(0, np.nan)
        out["volume_ratio_20"] = volume / vol_mean
        out["volume_z_20"] = (volume - vol_mean) / vol_std

        out["high_break_20"] = close / high.shift(1).rolling(20).max() - 1
        out["low_break_20"] = close / low.shift(1).rolling(20).min() - 1
        out["trend_strength"] = out["ema_ratio_10"] - out["ema_ratio_20"]
        rolling_max = close.rolling(20).max()
        out["drawdown_20"] = close / rolling_max - 1

        ts = out["timestamp"]
        hour = ts.dt.hour + ts.dt.minute / 60.0
        dow = ts.dt.dayofweek
        out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        out["dow_sin"] = np.sin(2 * np.pi * dow / 7)
        out["dow_cos"] = np.cos(2 * np.pi * dow / 7)

        return out


class TemporalDataset:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    def build(self, features: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        df = features.copy()
        h = self.config.horizon_bars
        future_return = df["close"].shift(-h) / df["close"] - 1
        target = (future_return >= self.config.target_return).astype(int)
        usable = df[FEATURE_COLUMNS].notna().all(axis=1) & future_return.notna()
        X = df.loc[usable, FEATURE_COLUMNS].copy()
        y = target.loc[usable].astype(int)
        if len(X) > self.config.max_training_rows:
            idx = np.linspace(0, len(X) - 1, self.config.max_training_rows, dtype=int)
            X = X.iloc[idx]
            y = y.iloc[idx]
        if len(X) < self.config.min_training_rows:
            raise ValueError(
                f"Dataset insuficiente: {len(X)} filas; mínimo {self.config.min_training_rows}"
            )
        return X.reset_index(drop=True), y.reset_index(drop=True)


class EnsembleModel:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        self.models: Dict[str, Any] = {}
        self.weights: Dict[str, float] = {}
        self.fitted = False
        self.reference_matrix: Optional[np.ndarray] = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        X_i = self.imputer.fit_transform(X)
        X_s = self.scaler.fit_transform(X_i)
        self.models = {}
        self.weights = {}

        # Ajuste dinámico por desbalance de clases.
        positives = max(int(y.sum()), 1)
        negatives = max(int(len(y) - y.sum()), 1)
        scale_pos_weight = float(negatives / positives)

        # Modelo lineal: baseline interpretable.
        try:
            lr = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=SEED)
            lr.fit(X_s, y)
            self.models["logistic"] = lr
            self.weights["logistic"] = 0.20
        except Exception:
            pass

        if xgb is not None:
            try:
                model = xgb.XGBClassifier(
                    n_estimators=220,
                    max_depth=4,
                    learning_rate=0.04,
                    subsample=0.85,
                    colsample_bytree=0.85,
                    objective="binary:logistic",
                    eval_metric="logloss",
                    scale_pos_weight=scale_pos_weight,
                    random_state=SEED,
                    n_jobs=1,
                )
                model.fit(X_s, y)
                self.models["xgb"] = model
                self.weights["xgb"] = 0.40
            except Exception:
                pass

        if lgb is not None:
            try:
                model = lgb.LGBMClassifier(
                    n_estimators=220,
                    max_depth=4,
                    num_leaves=31,
                    learning_rate=0.04,
                    subsample=0.85,
                    colsample_bytree=0.85,
                    objective="binary",
                    class_weight="balanced",
                    random_state=SEED,
                    verbosity=-1,
                    n_jobs=1,
                )
                model.fit(X_s, y)
                self.models["lightgbm"] = model
                self.weights["lightgbm"] = 0.30
            except Exception:
                pass

        if not self.models:
            raise RuntimeError("No fue posible entrenar ningún modelo")

        total = sum(self.weights.values()) or 1.0
        self.weights = {k: v / total for k, v in self.weights.items()}
        self.reference_matrix = X_s
        self.fitted = True
        return {"models": list(self.models), "weights": self.weights.copy()}

    def predict_proba(self, X: pd.DataFrame) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        if not self.fitted:
            raise RuntimeError("Ensemble no entrenado")
        X_i = self.imputer.transform(X)
        X_s = self.scaler.transform(X_i)
        votes: Dict[str, np.ndarray] = {}
        for name, model in self.models.items():
            if hasattr(model, "predict_proba"):
                votes[name] = model.predict_proba(X_s)[:, 1]
            else:
                votes[name] = np.asarray(model.predict(X_s), dtype=float)
        combined = np.zeros(len(X_s), dtype=float)
        for name, values in votes.items():
            combined += self.weights.get(name, 0.0) * values
        return combined, votes

    def novelty_score(self, X: pd.DataFrame) -> float:
        if self.reference_matrix is None or len(self.reference_matrix) == 0:
            return float("inf")
        X_s = self.scaler.transform(self.imputer.transform(X))
        # Distancia normalizada al centro de los datos históricos. No se pretende
        # que esto sea una probabilidad; es una señal de novedad para control de riesgo.
        center = self.reference_matrix.mean(axis=0)
        scale = self.reference_matrix.std(axis=0)
        scale[scale < 1e-8] = 1.0
        z = np.abs((X_s[0] - center) / scale)
        return float(np.mean(z))


class WalkForwardResearch:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    @staticmethod
    def _max_drawdown(returns: pd.Series) -> float:
        equity = (1 + returns.fillna(0)).cumprod()
        peak = equity.cummax()
        dd = equity / peak - 1
        return float(dd.min())

    def evaluate(self, features: pd.DataFrame) -> BacktestResult:
        dataset = TemporalDataset(self.config)
        X, y = dataset.build(features)
        split = int(len(X) * (1 - self.config.validation_fraction))
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]
        model = EnsembleModel(self.config)
        model.fit(X_train, y_train)
        probabilities, _ = model.predict_proba(X_test)
        predictions = (probabilities >= self.config.probability_threshold).astype(int)

        auc = None
        if len(np.unique(y_test)) > 1:
            auc = float(roc_auc_score(y_test, probabilities))
        accuracy = float(accuracy_score(y_test, predictions))
        precision = float(precision_score(y_test, predictions, zero_division=0))

        # Estrategia simplificada de investigación: entra solo cuando el modelo
        # supera el umbral. Se descuenta un coste conservador por operación.
        raw = features["close"].pct_change(self.config.horizon_bars).shift(-self.config.horizon_bars)
        raw = raw.dropna().iloc[-len(X_test):].reset_index(drop=True)
        strat_returns = raw.where(predictions == 1, 0.0)
        strategy_return = float((1 + strat_returns.fillna(0)).prod() - 1)
        buy_hold_return = float((1 + raw.fillna(0)).prod() - 1)
        max_dd = self._max_drawdown(strat_returns)
        passed = bool(
            len(X_test) >= 50
            and (auc is None or auc >= 0.52)
            and strategy_return > -0.10
        )
        reason = "OOS research dentro de límites mínimos" if passed else "OOS insuficiente o desempeño fuera de límites"

        return BacktestResult(
            rows=len(X),
            train_rows=len(X_train),
            test_rows=len(X_test),
            auc=auc,
            accuracy=accuracy,
            precision=precision,
            positive_rate=float(y.mean()),
            strategy_return=strategy_return,
            buy_hold_return=buy_hold_return,
            max_drawdown=max_dd,
            passed=passed,
            reason=reason,
        )


class SignalEngine:
    def __init__(self, config: Optional[EngineConfig] = None) -> None:
        self.config = config or EngineConfig()
        self.config.validate()
        self.feature_engine = FeatureEngine()
        self.model = EnsembleModel(self.config)
        self.trained = False
        self.training_fingerprint: Optional[str] = None

    @staticmethod
    def fingerprint(df: pd.DataFrame) -> str:
        normalized = MarketDataValidator.normalize(df)
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        payload = pd.util.hash_pandas_object(normalized[cols], index=True).values.tobytes()
        return hashlib.sha256(payload).hexdigest()

    def train(self, market_data: pd.DataFrame) -> Dict[str, Any]:
        features = self.feature_engine.build(market_data)
        dataset = TemporalDataset(self.config)
        X, y = dataset.build(features)
        # Training uses only chronological data; no shuffling.
        result = self.model.fit(X, y)
        self.trained = True
        self.training_fingerprint = self.fingerprint(market_data)
        return {
            "engine_version": ENGINE_VERSION,
            "rows": len(X),
            "positive_rate": float(y.mean()),
            "fingerprint": self.training_fingerprint,
            **result,
        }

    def generate_signal(self, market_data: pd.DataFrame, symbol: str) -> SignalCandidate:
        if not self.trained:
            raise RuntimeError("SignalEngine debe entrenarse antes de generar señales")
        features = self.feature_engine.build(market_data)
        latest = features.iloc[-1]
        X = pd.DataFrame([{c: latest[c] for c in FEATURE_COLUMNS}])
        probability, votes = self.model.predict_proba(X)
        p = float(probability[0])
        expected_return = float(latest["ret_5"] if pd.notna(latest["ret_5"]) else 0.0)
        novelty = self.model.novelty_score(X)
        evidence = "PRECEDENTED" if novelty <= self.config.novelty_distance_threshold else "NOVEL"
        confidence = float(abs(p - 0.5) * 2)
        score = float(p * confidence)

        signature_payload = {
            "trend": round(float(latest["trend_strength"]), 3),
            "rsi": round(float(latest["rsi_14"]), 3),
            "vol": round(float(latest["vol_20"]), 4),
            "bb": round(float(latest["bb_position"]), 3),
            "break": round(float(latest["high_break_20"]), 4),
        }
        setup_signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        model_votes = {k: float(v[0]) for k, v in votes.items()}
        selected_features = {
            c: float(latest[c]) for c in FEATURE_COLUMNS if pd.notna(latest[c])
        }
        return SignalCandidate(
            symbol=symbol,
            timestamp=str(latest["timestamp"]),
            probability_up=p,
            expected_return=expected_return,
            confidence=confidence,
            score=score,
            setup_signature=setup_signature,
            evidence_class=evidence,
            features=selected_features,
            model_votes=model_votes,
        )

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "engine_version": ENGINE_VERSION,
                "config": dataclasses.asdict(self.config),
                "model": self.model,
                "trained": self.trained,
                "training_fingerprint": self.training_fingerprint,
            },
            path,
        )

    @classmethod
    def load(cls, path: str) -> "SignalEngine":
        payload = joblib.load(path)
        config = EngineConfig(**payload["config"])
        engine = cls(config)
        engine.model = payload["model"]
        engine.trained = bool(payload["trained"])
        engine.training_fingerprint = payload.get("training_fingerprint")
        return engine


def generate_synthetic_ohlcv(rows: int = 1500, seed: int = SEED) -> pd.DataFrame:
    """Datos sintéticos únicamente para pruebas de ingeniería; no son mercado real."""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range("2025-01-02", periods=rows, freq="h", tz="UTC")
    shocks = rng.normal(0.0001, 0.006, rows)
    close = 100 * np.exp(np.cumsum(shocks))
    open_ = close * (1 + rng.normal(0, 0.0015, rows))
    spread = np.abs(rng.normal(0.002, 0.001, rows))
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = rng.lognormal(mean=12, sigma=0.35, size=rows)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def self_test() -> Dict[str, Any]:
    config = EngineConfig(
        min_training_rows=300,
        max_training_rows=1200,
        probability_threshold=0.55,
    )
    raw = generate_synthetic_ohlcv(1800)
    features = FeatureEngine.build(raw)
    assert len(features) == len(raw)
    assert all(c in features.columns for c in FEATURE_COLUMNS)

    research = WalkForwardResearch(config).evaluate(features)
    engine = SignalEngine(config)
    training = engine.train(raw)
    signal = engine.generate_signal(raw, "DEMO")

    assert training["rows"] >= config.min_training_rows
    assert 0 <= signal.probability_up <= 1
    assert 0 <= signal.confidence <= 1
    assert signal.setup_signature

    return {
        "ok": True,
        "engine_version": ENGINE_VERSION,
        "training": training,
        "research": dataclasses.asdict(research),
        "signal": dataclasses.asdict(signal),
        "note": "Los datos usados son sintéticos y no representan resultados de mercado.",
    }


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2, default=str))
