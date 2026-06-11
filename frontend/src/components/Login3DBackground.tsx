import { useEffect, useRef } from "react";
import * as THREE from "three";

export function Login3DBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const isMobile = window.innerWidth < 860;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: !isMobile });
    } catch {
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x020b02, 1);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x040804, 0.016);

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 400);
    camera.position.set(0, 7, 26);
    camera.lookAt(0, 0, 0);

    // ── Layer 1: Wireframe terrain ─────────────────────────────────────────────
    const terrainGeo = new THREE.PlaneGeometry(160, 90, 90, 45);
    terrainGeo.rotateX(-Math.PI / 2);
    const terrainMat = new THREE.MeshBasicMaterial({
      color: 0x1a3a08,
      wireframe: true,
      transparent: true,
      opacity: 0.35,
    });
    const terrain = new THREE.Mesh(terrainGeo, terrainMat);
    terrain.position.y = -4;
    scene.add(terrain);

    // ── Layer 2: Marching price line ───────────────────────────────────────────
    const LINE_PTS = 220;
    const priceHistory: number[] = Array.from({ length: LINE_PTS }, (_, i) =>
      Math.sin(i * 0.15) * 2 + Math.sin(i * 0.07) * 1
    );
    const lineGeo = new THREE.BufferGeometry();
    const linePositions = new Float32Array(LINE_PTS * 3);
    for (let i = 0; i < LINE_PTS; i++) {
      linePositions[i * 3]     = (i / (LINE_PTS - 1)) * 40 - 20;
      linePositions[i * 3 + 1] = priceHistory[i];
      linePositions[i * 3 + 2] = -5;
    }
    lineGeo.setAttribute("position", new THREE.BufferAttribute(linePositions, 3));
    const lineMat = new THREE.LineBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0.7 });
    const priceLine = new THREE.Line(lineGeo, lineMat);
    scene.add(priceLine);
    let lastLineFrame = 0;

    // ── Layer 3: Candlestick group ─────────────────────────────────────────────
    const candleGroup = new THREE.Group();
    const candleGeos: THREE.BufferGeometry[] = [];
    const NUM_CANDLES = 40;
    const bullMat = new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0.55 });
    const bearMat = new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.45 });
    const wickMat = new THREE.LineBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0.4 });

    for (let i = 0; i < NUM_CANDLES; i++) {
      const isBull = Math.random() > 0.42;
      const x = (i - NUM_CANDLES / 2) * 1.1;
      const bodyH = 0.3 + Math.random() * 1.5;
      const bodyY = Math.random() * 3 - 1.5;

      const bodyGeo = new THREE.BoxGeometry(0.45, bodyH, 0.45);
      candleGeos.push(bodyGeo);
      const body = new THREE.Mesh(bodyGeo, isBull ? bullMat : bearMat);
      body.position.set(x, bodyY, -10);
      candleGroup.add(body);

      const wickPts = [
        new THREE.Vector3(x, bodyY - bodyH / 2 - Math.random() * 0.6, -10),
        new THREE.Vector3(x, bodyY + bodyH / 2 + Math.random() * 0.6, -10),
      ];
      const wickGeo = new THREE.BufferGeometry().setFromPoints(wickPts);
      candleGeos.push(wickGeo);
      candleGroup.add(new THREE.Line(wickGeo, wickMat));
    }
    scene.add(candleGroup);

    // ── Layer 4: Particles ─────────────────────────────────────────────────────
    const PARTICLE_COUNT = isMobile ? 300 : 600;
    const pPos = new Float32Array(PARTICLE_COUNT * 3);
    const pVel = new Float32Array(PARTICLE_COUNT);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      pPos[i * 3]     = (Math.random() - 0.5) * 80;
      pPos[i * 3 + 1] = (Math.random() - 0.5) * 40;
      pPos[i * 3 + 2] = (Math.random() - 0.5) * 40;
      pVel[i] = 0.006 + Math.random() * 0.018;
    }
    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0x4ade80,
      size: 0.12,
      transparent: true,
      opacity: 0.45,
      sizeAttenuation: true,
    });
    scene.add(new THREE.Points(particleGeo, particleMat));

    // ── Layer 5: Mouse parallax ────────────────────────────────────────────────
    let mouseX = 0, mouseY = 0, camX = 0, camY = 0;
    const onMouseMove = (e: MouseEvent) => {
      mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("mousemove", onMouseMove);

    let paused = false;
    const onVisibility = () => { paused = document.visibilityState === "hidden"; };
    document.addEventListener("visibilitychange", onVisibility);

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", onResize);

    // ── Animation ─────────────────────────────────────────────────────────────
    let rafId = 0;
    let frame = 0;

    const tick = () => {
      rafId = requestAnimationFrame(tick);
      if (paused) return;
      frame++;

      // Terrain sine wave
      const tp = terrainGeo.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < tp.count; i++) {
        const x = tp.getX(i);
        const z = tp.getZ(i);
        tp.setY(i, Math.sin(x * 0.05 + frame * 0.012) * 1.2 + Math.sin(z * 0.07 + frame * 0.008) * 0.8);
      }
      tp.needsUpdate = true;

      // Price line march at ~30fps
      if (frame - lastLineFrame >= 2) {
        lastLineFrame = frame;
        const last = priceHistory[priceHistory.length - 1];
        let next = last + (Math.random() - 0.5) * 0.5;
        next = Math.max(-4, Math.min(4, next));
        priceHistory.push(next);
        priceHistory.shift();
        const lp = priceLine.geometry.attributes.position as THREE.BufferAttribute;
        for (let i = 0; i < LINE_PTS; i++) lp.setY(i, priceHistory[i]);
        lp.needsUpdate = true;
      }

      // Candlestick slow rotation
      candleGroup.rotation.y += 0.0015;

      // Particles drift upward
      const pa = particleGeo.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const y = pa.getY(i) + pVel[i];
        pa.setY(i, y > 20 ? -20 : y);
      }
      pa.needsUpdate = true;

      // Camera parallax ease
      camX += (mouseX * 2.5 - camX) * 0.04;
      camY += (-mouseY * 1.5 - camY) * 0.04;
      camera.position.set(camX, 7 + camY, 26);
      camera.lookAt(0, 0, 0);

      renderer.render(scene, camera);
    };

    renderer.render(scene, camera);
    if (!reducedMotion) tick();

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      terrainGeo.dispose();
      terrainMat.dispose();
      lineGeo.dispose();
      lineMat.dispose();
      candleGeos.forEach(g => g.dispose());
      bullMat.dispose();
      bearMat.dispose();
      wickMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        zIndex: 0,
        pointerEvents: "none",
        display: "block",
      }}
    />
  );
}
