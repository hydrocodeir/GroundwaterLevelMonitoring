/**
 * A small, dependency-free, shared-camera renderer for two aquifer snapshots.
 *
 * The input heads and bottoms must be elevations in the same vertical datum.
 * A missing bottom is shown against a synthetic reference plane; callers must
 * not present that reference as a measured bedrock surface or absolute storage.
 */

const PALETTES = {
  before: {
    top: Array.from({ length: 24 }, (_, i) =>
      `hsl(199 78% ${44 + Math.round((i / 23) * 18)}%)`),
    wall: ['#135b83', '#176b95', '#1c779e', '#105173'],
    edge: 'rgba(213, 245, 255, .22)',
  },
  after: {
    top: Array.from({ length: 24 }, (_, i) =>
      `hsl(174 62% ${35 + Math.round((i / 23) * 17)}%)`),
    wall: ['#125f5c', '#18756d', '#208078', '#105851'],
    edge: 'rgba(217, 255, 246, .22)',
  },
};

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const WET_EPSILON = 1e-10;

function interpolateVertex(a, b, fraction) {
  const vertex = {};
  for (const key of ['x', 'y', 'before', 'after', 'bottom']) {
    vertex[key] = finite(a[key]) && finite(b[key])
      ? a[key] + (b[key] - a[key]) * fraction : null;
  }
  return vertex;
}

// Head and floor are linear inside each triangle. Their intersection therefore
// clips a wet polygon exactly; a dry corner must never be lifted into water.
function clipSurfaceTriangle(triangle, phase, keepWet = true) {
  const gap = (vertex) => (vertex[phase] - vertex.bottom) * (keepWet ? 1 : -1);
  if (keepWet ? !triangle.some((vertex) => gap(vertex) > WET_EPSILON)
    : triangle.every((vertex) => gap(vertex) < 0)) return [];
  const polygon = [];
  let previous = triangle[triangle.length - 1];
  for (const current of triangle) {
    const previousGap = gap(previous);
    const currentGap = gap(current);
    if ((previousGap >= 0) !== (currentGap >= 0)) {
      const intersection = interpolateVertex(previous, current,
        previousGap / (previousGap - currentGap));
      intersection[phase] = intersection.bottom;
      polygon.push(intersection);
    }
    if (currentGap >= 0) polygon.push(current);
    previous = current;
  }
  return polygon.filter((vertex, index) => {
    const previousVertex = polygon[(index + polygon.length - 1) % polygon.length];
    return Math.hypot(vertex.x - previousVertex.x, vertex.y - previousVertex.y) > WET_EPSILON;
  });
}

function clipPositiveSegment(a, b, gap) {
  const gapA = gap(a);
  const gapB = gap(b);
  if (Math.max(gapA, gapB) <= WET_EPSILON) return null;
  if (gapA >= 0 && gapB >= 0) return [a, b];
  const intersection = interpolateVertex(a, b, gapA / (gapA - gapB));
  return gapA < 0 ? [intersection, b] : [a, intersection];
}

function prepareGrid(data) {
  const grid = data?.grid;
  const cols = Math.trunc(grid?.cols);
  const rows = Math.trunc(grid?.rows);
  const raw = grid?.points;
  if (!Array.isArray(raw) || cols < 2 || rows < 2 || raw.length < cols * rows) {
    return null;
  }

  const points = raw.slice(0, cols * rows).map((item) => {
    if (!Array.isArray(item)) return null;
    const [lon, lat, before, after, bottom, inside] = item;
    if (!finite(lon) || !finite(lat) || inside === false || inside === 0) return null;
    return {
      lon, lat,
      before: finite(before) ? before : null,
      after: finite(after) ? after : null,
      bottom: finite(bottom) ? bottom : null,
    };
  });

  const validXY = points.filter(Boolean);
  const heads = validXY.flatMap((point) => [point.before, point.after]).filter(finite);
  if (validXY.length < 4 || !heads.length) return null;

  const minLon = Math.min(...validXY.map((point) => point.lon));
  const maxLon = Math.max(...validXY.map((point) => point.lon));
  const minLat = Math.min(...validXY.map((point) => point.lat));
  const maxLat = Math.max(...validXY.map((point) => point.lat));
  const meanLat = (minLat + maxLat) / 2;
  const metresPerLon = 111320 * Math.cos(meanLat * Math.PI / 180);
  const metresPerLat = 111320;
  const spanX = Math.max((maxLon - minLon) * metresPerLon, 1);
  const spanY = Math.max((maxLat - minLat) * metresPerLat, 1);
  const spanXY = Math.max(spanX, spanY);
  const centreLon = (minLon + maxLon) / 2;
  const centreLat = (minLat + maxLat) / 2;
  const minHead = Math.min(...heads);
  const maxHead = Math.max(...heads);
  const headRange = maxHead - minHead;
  const fallbackBottom = minHead - Math.max(5, headRange * .35);
  const bottoms = validXY.map((point) => point.bottom).filter(finite);
  const hasMissingBottom = validXY.some((point) => point.bottom === null);
  const bedrockScenario = grid.bedrock_source === 'karat_scenario' && !hasMissingBottom;
  const minimumBottom = bottoms.length
    ? Math.min(...bottoms, ...(hasMissingBottom ? [fallbackBottom] : []))
    : fallbackBottom;
  const maximumBottom = bottoms.length ? Math.max(...bottoms) : fallbackBottom;
  const minimumElevation = Math.min(minHead, minimumBottom);
  const verticalRange = Math.max(1, Math.max(maxHead, maximumBottom) - minimumElevation);
  // Both scenes share this exact scale. It is intentionally exaggerated for
  // visibility; the physical elevation values are retained in the data.
  const verticalScale = .58 / verticalRange;
  const xy = (lon, lat) => ({
    x: ((lon - centreLon) * metresPerLon) / spanXY,
    y: ((lat - centreLat) * metresPerLat) / spanXY,
  });
  const z = (height) => (height - minimumElevation) * verticalScale;

  const vertices = points.map((point) => {
    if (!point) return null;
    const horizontal = xy(point.lon, point.lat);
    return {
      ...horizontal,
      before: point.before === null ? null : z(point.before),
      after: point.after === null ? null : z(point.after),
      bottom: z(point.bottom === null ? fallbackBottom : point.bottom),
    };
  });

  const at = (row, col) => vertices[row * cols + col];
  const scenes = {};
  for (const phase of ['before', 'after']) {
    const occupied = Array.from({ length: rows - 1 }, () => Array(cols - 1).fill(false));
    for (let row = 0; row < rows - 1; row++) {
      for (let col = 0; col < cols - 1; col++) {
        const corners = [at(row, col), at(row, col + 1), at(row + 1, col + 1), at(row + 1, col)];
        occupied[row][col] = corners.every((point) => point && point[phase] !== null);
      }
    }

    const topFaces = [];
    const floorFaces = [];
    const floorRim = [];
    const rim = [];
    const declineFaces = [];
    for (let row = 0; row < rows - 1; row++) {
      for (let col = 0; col < cols - 1; col++) {
        if (!occupied[row][col]) continue;
        const corners = [at(row, col), at(row, col + 1), at(row + 1, col + 1), at(row + 1, col)];
        const base = corners.map((point) => [point.x, point.y, point.bottom]);
        for (const indices of [[0, 1, 2], [0, 2, 3]]) {
          const triangle = indices.map((index) => corners[index]);
          // From the camera's above-ground view, opaque water hides submerged
          // floor. Clip it away so a floor centroid cannot overpaint that water.
          const visibleFloor = bedrockScenario ? triangle : clipSurfaceTriangle(triangle, phase, false);
          if (visibleFloor.length >= 3) {
            floorFaces.push({ vertices: visibleFloor.map((point) => [point.x, point.y, point.bottom]), kind: 'floor' });
          }
          const wetPolygon = clipSurfaceTriangle(triangle, phase);
          if (wetPolygon.length < 3) continue;
          const top = wetPolygon.map((point) => [point.x, point.y, point[phase]]);
          const averageHeight = top.reduce((sum, point) => sum + point[2], 0) / top.length;
          topFaces.push({ vertices: top, kind: 'top', tone: clamp(Math.round(averageHeight / .58 * 23), 0, 23) });
          for (let edge = 0; edge < wetPolygon.length; edge++) {
            const next = (edge + 1) % wetPolygon.length;
            if (Math.abs(wetPolygon[edge][phase] - wetPolygon[edge].bottom) <= WET_EPSILON
                && Math.abs(wetPolygon[next][phase] - wetPolygon[next].bottom) <= WET_EPSILON) {
              rim.push([top[edge], top[next]]);
            }
          }
        }
        const floorNeighbours = [
          row > 0 && occupied[row - 1][col],
          col < cols - 2 && occupied[row][col + 1],
          row < rows - 2 && occupied[row + 1][col],
          col > 0 && occupied[row][col - 1],
        ];
        for (let edge = 0; edge < 4; edge++) {
          if (!floorNeighbours[edge]) floorRim.push([base[edge], base[(edge + 1) % 4]]);
        }
        for (let edge = 0; edge < 4; edge++) {
          if (floorNeighbours[edge]) continue;
          const next = (edge + 1) % 4;
          const wetSegment = clipPositiveSegment(corners[edge], corners[next],
            (point) => point[phase] - point.bottom);
          if (!wetSegment) continue;
          const [a, b] = wetSegment;
          const topA = [a.x, a.y, a[phase]];
          const topB = [b.x, b.y, b[phase]];
          topFaces.push({
            vertices: [topA, topB, [b.x, b.y, b.bottom], [a.x, a.y, a.bottom]],
            kind: 'wall',
            tone: edge,
          });
          if (phase === 'after' && finite(a.before) && finite(b.before)) {
            const declineSegment = clipPositiveSegment(a, b, (point) => point.before - point.after);
            if (declineSegment) {
              const [oldA, oldB] = declineSegment;
              declineFaces.push({
                vertices: [
                  [oldA.x, oldA.y, oldA.before], [oldB.x, oldB.y, oldB.before],
                  [oldB.x, oldB.y, oldB.after], [oldA.x, oldA.y, oldA.after],
                ],
                kind: 'decline',
              });
            }
          }
          rim.push([topA, topB]);
        }
      }
    }
    scenes[phase] = { topFaces, floorFaces, floorRim, rim, declineFaces };
  }

  const outlines = Array.isArray(grid.outlines) ? grid.outlines
    .filter(Array.isArray)
    .map((ring) => ring.filter((point) => Array.isArray(point) && finite(point[0]) && finite(point[1]))
      .map(([lon, lat]) => {
        const point = xy(lon, lat);
        return [point.x, point.y, 0];
      }))
    .filter((ring) => ring.length > 1) : [];

  return {
    scenes,
    outlines,
    verticalExaggeration: spanXY * verticalScale,
    bedrockReal: grid.bedrock_real === true && !hasMissingBottom,
    bedrockScenario,
  };
}

function paintBackground(ctx, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, '#081827');
  gradient.addColorStop(.55, '#10283a');
  gradient.addColorStop(1, '#071520');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  const glow = ctx.createRadialGradient(width * .5, height * .55, 0, width * .5, height * .55, Math.max(width, height) * .7);
  glow.addColorStop(0, 'rgba(59, 102, 130, .18)');
  glow.addColorStop(1, 'rgba(59, 102, 130, 0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, height);
}

function paintEmpty(ctx, width, height) {
  paintBackground(ctx, width, height);
  ctx.fillStyle = '#cbd9e5';
  ctx.font = '14px Tahoma, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('دادهٔ کافی برای نمایش سه‌بعدی وجود ندارد', width / 2, height / 2);
}

/**
 * Mounts two synchronized scenes and returns a function that removes observers
 * and event listeners. Pointer drag rotates; mouse wheel zooms both scenes.
 * The returned cleanup function exposes `verticalExaggeration` for UI labels.
 */
export function mountAquiferScenes({ beforeCanvas, afterCanvas, data }) {
  if (!beforeCanvas?.getContext || !afterCanvas?.getContext) {
    throw new TypeError('Both aquifer scene canvases are required.');
  }

  const prepared = prepareGrid(data);
  const canvases = [beforeCanvas, afterCanvas];
  const contexts = canvases.map((canvas) => canvas.getContext('2d'));
  if (contexts.some((ctx) => !ctx)) throw new Error('Canvas 2D is unavailable.');

  const dimensions = canvases.map(() => ({ width: 0, height: 0 }));
  const initialZoom = prepared?.bedrockScenario ? 1.25 : 1;
  const camera = { yaw: 0, pitch: .63, zoom: initialZoom };
  const originalTouchActions = canvases.map((canvas) => canvas.style.touchAction);
  let pendingFrame = 0;
  let disposed = false;
  let dragging = null;

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    for (let i = 0; i < canvases.length; i++) {
      const canvas = canvases[i];
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, rect.width || canvas.clientWidth || 300);
      const height = Math.max(1, rect.height || canvas.clientHeight || 300);
      dimensions[i] = { width, height };
      const backingWidth = Math.max(1, Math.round(width * ratio));
      const backingHeight = Math.max(1, Math.round(height * ratio));
      if (canvas.width !== backingWidth) canvas.width = backingWidth;
      if (canvas.height !== backingHeight) canvas.height = backingHeight;
      contexts[i].setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    requestPaint();
  }

  function requestPaint() {
    if (!disposed && !pendingFrame) pendingFrame = requestAnimationFrame(paint);
  }

  function paint() {
    pendingFrame = 0;
    const commonSize = Math.max(1, Math.min(...dimensions.map(({ width, height }) => Math.min(width, height))));
    const scale = commonSize * .62 * camera.zoom;
    for (let i = 0; i < 2; i++) {
      const { width, height } = dimensions[i];
      const ctx = contexts[i];
      ctx.clearRect(0, 0, width, height);
      if (!prepared) {
        paintEmpty(ctx, width, height);
        continue;
      }
      const phase = i === 0 ? 'before' : 'after';
      const palette = PALETTES[phase];
      const sinYaw = Math.sin(camera.yaw);
      const cosYaw = Math.cos(camera.yaw);
      const sinPitch = Math.sin(camera.pitch);
      const cosPitch = Math.cos(camera.pitch);
      const centreX = width / 2;
      const centreY = height * .69;
      const project = ([x, y, z]) => {
        const lateral = x * cosYaw - y * sinYaw;
        const depth = x * sinYaw + y * cosYaw;
        return {
          x: centreX + lateral * scale,
          // Geographic north is +y; screen y grows downward.
          y: centreY + (-depth * sinPitch - z * cosPitch) * scale,
          // Larger values are nearer the camera, so ascending sort paints far first.
          depth: -depth * cosPitch + z * sinPitch,
        };
      };
      const drawFace = (face, fill, alpha = 1) => {
        const projected = face.vertices.map(project);
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(projected[0].x, projected[0].y);
        for (let j = 1; j < projected.length; j++) ctx.lineTo(projected[j].x, projected[j].y);
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.lineWidth = face.kind === 'top' ? .55 : .8;
        ctx.strokeStyle = face.kind === 'top' ? palette.edge
          : face.kind === 'floor' && prepared.bedrockScenario ? 'rgba(255, 228, 183, .34)' : fill;
        ctx.stroke();
        ctx.restore();
      };
      const sortDepth = (face) => face.vertices.reduce((sum, vertex) => sum + project(vertex).depth, 0) / face.vertices.length;

      paintBackground(ctx, width, height);
      const scene = prepared.scenes[phase];
      if (!scene.floorFaces.length && !scene.topFaces.length) {
        paintEmpty(ctx, width, height);
        continue;
      }
      const floorColour = prepared.bedrockScenario ? '#967654'
        : prepared.bedrockReal ? '#34485a' : '#3a4651';
      // Opaque dry bedrock can hide water farther from the camera. Karat's
      // translucent scenario keeps its floor underneath the water overlay.
      const faceLayers = prepared.bedrockScenario
        ? [scene.floorFaces, scene.topFaces] : [[...scene.floorFaces, ...scene.topFaces]];
      for (const layer of faceLayers) {
        for (const face of [...layer].sort((a, b) => sortDepth(a) - sortDepth(b))) {
          drawFace(face, face.kind === 'floor' ? floorColour
            : face.kind === 'top' ? palette.top[face.tone] : palette.wall[face.tone],
          prepared.bedrockScenario && face.kind !== 'floor' ? face.kind === 'top' ? .72 : .66 : 1);
        }
      }
      if (phase === 'after') {
        for (const face of [...scene.declineFaces].sort((a, b) => sortDepth(a) - sortDepth(b))) {
          drawFace(face, 'rgba(255, 172, 105, .56)');
        }
      }

      if (prepared.bedrockScenario) {
        ctx.save();
        ctx.strokeStyle = 'rgba(255, 213, 153, .86)';
        ctx.lineWidth = 1.6;
        ctx.setLineDash([4, 3]);
        for (const [start, end] of scene.floorRim) {
          const a = project(start);
          const b = project(end);
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
        ctx.restore();
      }

      ctx.save();
      ctx.strokeStyle = 'rgba(198, 218, 230, .54)';
      ctx.lineWidth = 1.15;
      ctx.setLineDash([4, 4]);
      for (const ring of prepared.outlines) {
        ctx.beginPath();
        const first = project(ring[0]);
        ctx.moveTo(first.x, first.y);
        for (let j = 1; j < ring.length; j++) {
          const point = project(ring[j]);
          ctx.lineTo(point.x, point.y);
        }
        ctx.closePath();
        ctx.stroke();
      }
      ctx.restore();

      if (phase === 'after' && prepared.scenes.before.rim.length) {
        ctx.save();
        ctx.strokeStyle = 'rgba(173, 224, 255, .78)';
        ctx.lineWidth = 1.4;
        ctx.setLineDash([5, 4]);
        for (const edge of prepared.scenes.before.rim) {
          const a = project(edge[0]);
          const b = project(edge[1]);
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
        ctx.restore();
      }

      // A live compass stays accurate after dragging rotates the shared camera.
      const origin = project([0, 0, 0]);
      const directions = [
        { label: 'N', point: project([0, 1, 0]), color: '#8ee7f0' },
        { label: 'E', point: project([1, 0, 0]), color: '#daeaf3' },
      ];
      const compassX = width - 57;
      const compassY = 55;
      ctx.save();
      ctx.fillStyle = 'rgba(4, 19, 32, .72)';
      ctx.beginPath();
      ctx.arc(compassX, compassY, 39, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.font = 'bold 11px Arial, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const direction of directions) {
        const dx = direction.point.x - origin.x;
        const dy = direction.point.y - origin.y;
        const length = Math.hypot(dx, dy) || 1;
        const ux = dx / length;
        const uy = dy / length;
        ctx.strokeStyle = direction.color;
        ctx.fillStyle = direction.color;
        ctx.beginPath();
        ctx.moveTo(compassX, compassY);
        ctx.lineTo(compassX + ux * 23, compassY + uy * 23);
        ctx.stroke();
        ctx.fillText(direction.label, compassX + ux * 31, compassY + uy * 31);
      }
      ctx.restore();
    }
  }

  function onPointerDown(event) {
    if (event.button !== 0 || dragging) return;
    dragging = { canvas: event.currentTarget, id: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event) {
    if (!dragging || dragging.canvas !== event.currentTarget || dragging.id !== event.pointerId) return;
    camera.yaw += (event.clientX - dragging.x) * .008;
    camera.pitch = clamp(camera.pitch + (event.clientY - dragging.y) * .006, .18, 1.30);
    dragging.x = event.clientX;
    dragging.y = event.clientY;
    requestPaint();
  }

  function onPointerEnd(event) {
    if (dragging?.canvas === event.currentTarget && dragging.id === event.pointerId) dragging = null;
  }

  function onWheel(event) {
    event.preventDefault();
    camera.zoom = clamp(camera.zoom * Math.exp(-event.deltaY * .0012), .55, 2.4);
    requestPaint();
  }

  function onDoubleClick(event) {
    event.preventDefault();
    camera.yaw = 0;
    camera.pitch = .63;
    camera.zoom = initialZoom;
    requestPaint();
  }

  for (const canvas of canvases) {
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerEnd);
    canvas.addEventListener('pointercancel', onPointerEnd);
    canvas.addEventListener('lostpointercapture', onPointerEnd);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', onDoubleClick);
    canvas.style.touchAction = 'none';
  }

  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
  if (observer) canvases.forEach((canvas) => observer.observe(canvas));
  else window.addEventListener('resize', resize);
  resize();

  function cleanup() {
    disposed = true;
    if (pendingFrame) cancelAnimationFrame(pendingFrame);
    observer?.disconnect();
    if (!observer) window.removeEventListener('resize', resize);
    for (const [index, canvas] of canvases.entries()) {
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerEnd);
      canvas.removeEventListener('pointercancel', onPointerEnd);
      canvas.removeEventListener('lostpointercapture', onPointerEnd);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('dblclick', onDoubleClick);
      canvas.style.touchAction = originalTouchActions[index];
    }
  }
  cleanup.verticalExaggeration = prepared?.verticalExaggeration ?? null;
  cleanup.bedrockReal = prepared?.bedrockReal ?? false;
  return cleanup;
}
