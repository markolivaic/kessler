/**
 * The globe: a graticule, a coastline, and nineteen thousand points over it.
 *
 * No photographic texture. A satellite catalogue is a plotting problem and the
 * domain's own convention for it is a wireframe chart, which also leaves the points
 * as the only bright thing on screen rather than competing with a rendered ocean.
 */

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

import { groundColour, ink, isLightGround, rgb, rgbFor } from "./palette";

/** Scene units are thousands of kilometres, so the Earth is about 6.4 across. */
export const SCENE_SCALE = 1 / 1000;
const EARTH_RADIUS_KM = 6378.137;
const EARTH_RADIUS = EARTH_RADIUS_KM * SCENE_SCALE;

/** Earth-fixed kilometres into scene coordinates, north pole up. */
export function toScene(x: number, y: number, z: number): [number, number, number] {
  return [x * SCENE_SCALE, z * SCENE_SCALE, -y * SCENE_SCALE];
}

function lonLatToScene(lon: number, lat: number, radius: number): [number, number, number] {
  const phi = (lat * Math.PI) / 180;
  const lambda = (lon * Math.PI) / 180;
  return toScene(
    (radius * Math.cos(phi) * Math.cos(lambda)) / SCENE_SCALE,
    (radius * Math.cos(phi) * Math.sin(lambda)) / SCENE_SCALE,
    (radius * Math.sin(phi)) / SCENE_SCALE,
  );
}

/**
 * Ground dependent furniture. The comparison in docs/design.md is only worth
 * anything if the pale version is built properly rather than left half done, so the
 * shell, graticule and coastline all get a light counterpart.
 */
function furniture() {
  return isLightGround()
    ? { shell: 0xdedad1, graticule: 0xc3bdb1, coastline: 0x7089a0 }
    : { shell: 0x0b1a26, graticule: 0x223040, coastline: 0x5a86ad };
}

function graticule(radius: number, step = 30): THREE.LineSegments {
  const points: number[] = [];
  const push = (a: [number, number, number], b: [number, number, number]) => {
    points.push(a[0], a[1], a[2], b[0], b[1], b[2]);
  };
  for (let lat = -60; lat <= 60; lat += step) {
    for (let lon = -180; lon < 180; lon += 4) {
      push(lonLatToScene(lon, lat, radius), lonLatToScene(lon + 4, lat, radius));
    }
  }
  for (let lon = -180; lon < 180; lon += step) {
    for (let lat = -88; lat < 88; lat += 4) {
      push(lonLatToScene(lon, lat, radius), lonLatToScene(lon, lat + 4, radius));
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color: furniture().graticule, transparent: true, opacity: 0.55 }),
  );
}

function coastline(topology: Topology, radius: number): THREE.LineSegments {
  const land = feature(topology, topology.objects.land) as GeoJSON.FeatureCollection;
  const points: number[] = [];
  const addRing = (ring: number[][]) => {
    for (let i = 0; i + 1 < ring.length; i += 1) {
      const a = lonLatToScene(ring[i][0], ring[i][1], radius);
      const b = lonLatToScene(ring[i + 1][0], ring[i + 1][1], radius);
      points.push(a[0], a[1], a[2], b[0], b[1], b[2]);
    }
  };
  for (const shape of land.features) {
    const geometry = shape.geometry;
    if (geometry.type === "Polygon") geometry.coordinates.forEach(addRing);
    else if (geometry.type === "MultiPolygon")
      geometry.coordinates.forEach((polygon) => polygon.forEach(addRing));
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  // Bright enough to orient by, still dimmer than any point drawn over it. At the
  // first value tried, 0x3d5570, the coastline was invisible under the point field
  // and the globe had nothing to read position against.
  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color: furniture().coastline }),
  );
}

export interface GlobeHandle {
  setPositions(positions: Float32Array, velocities: Float32Array, ok: Uint8Array): void;
  advance(seconds: number): void;
  setTypes(types: string[]): void;
  setHighlight(selected: number | null, partner: number | null): void;
  pick(clientX: number, clientY: number): number | null;
  focus(index: number): void;
  resize(): void;
  render(): void;
  dispose(): void;
  /** For the light-against-dark comparison the design brief commits to. */
  setGround(colour: string): void;
  refreshTheme(): void;
  canvas: HTMLCanvasElement;
}

export async function createGlobe(container: HTMLElement, count: number): Promise<GlobeHandle> {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(groundColour());

  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 500);
  camera.position.set(14, 9, 16);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    // So the canvas can be read back with toDataURL. docs/design.md commits to
    // settling the dark ground against a pale one by rendering the identical frame
    // both ways; without this the buffer is discarded after each present and that
    // evidence can only be produced by photographing a screen.
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 7.2;
  controls.maxDistance = 90;
  controls.rotateSpeed = 0.5;

  // A solid sphere slightly inside the wireframe, so points behind the Earth are
  // occluded instead of showing through and doubling the apparent population.
  const shell = new THREE.Mesh(
    new THREE.SphereGeometry(EARTH_RADIUS * 0.995, 64, 48),
    new THREE.MeshBasicMaterial({ color: furniture().shell }),
  );
  scene.add(shell);
  scene.add(graticule(EARTH_RADIUS));

  try {
    const topology = (await import("world-atlas/land-110m.json")).default as unknown as Topology;
    scene.add(coastline(topology, EARTH_RADIUS * 1.001));
  } catch (error) {
    // The graticule alone still orients the view, so this is not fatal. It is loud
    // though: swallowing it silently would mean a globe that quietly lost its
    // coastline and nobody finding out until someone looked at a recording.
    console.error("kessler: coastline data failed to load, falling back to graticule", error);
  }

  const positionAttribute = new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3);
  const colourAttribute = new THREE.Float32BufferAttribute(new Float32Array(count * 3), 3);
  const sizeAttribute = new THREE.Float32BufferAttribute(new Float32Array(count), 1);
  positionAttribute.setUsage(THREE.DynamicDrawUsage);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", positionAttribute);
  geometry.setAttribute("colour", colourAttribute);
  geometry.setAttribute("size", sizeAttribute);

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      // gl_PointSize is in framebuffer pixels, so without this the points are
      // physically larger on a low density display than a high density one.
      uPixelRatio: { value: renderer.getPixelRatio() },
    },
    vertexShader: `
      attribute vec3 colour;
      attribute float size;
      uniform float uPixelRatio;
      varying vec3 vColour;
      void main() {
        vColour = colour;
        vec4 view = modelViewMatrix * vec4(position, 1.0);
        // 28 is not a taste constant. Scene units are thousands of kilometres and
        // the camera sits about 23 of them out, so this puts an ordinary object at
        // roughly two and a half CSS pixels at the default zoom. The first version
        // used 300, which drew every point about twenty pixels across: 2,637 debris
        // objects then merged into one opaque shell that hid the Earth and made
        // debris look like the bulk of the population instead of 14% of it.
        gl_PointSize = clamp(
          size * uPixelRatio * (28.0 / -view.z),
          uPixelRatio,
          20.0 * uPixelRatio
        );
        gl_Position = projectionMatrix * view;
      }`,
    fragmentShader: `
      varying vec3 vColour;
      void main() {
        vec2 offset = gl_PointCoord - vec2(0.5);
        float d = dot(offset, offset);
        if (d > 0.25) discard;
        float edge = smoothstep(0.25, 0.06, d);
        gl_FragColor = vec4(vColour, edge);
      }`,
  });

  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  scene.add(points);

  // A ring, not a bigger dot.
  //
  // The selected object was originally just white and 3.2x size. That passes the
  // palette distance rule numerically, white sits 0.52 from the payload blue, and
  // it still failed the only job it has: among nineteen thousand pale dots a
  // slightly whiter, slightly larger pale dot cannot be found. Size and hue are the
  // wrong channel here. Shape is the right one, because nothing else on the globe
  // is an annulus.
  const markerGeometry = new THREE.BufferGeometry();
  markerGeometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(new Float32Array(2 * 3), 3).setUsage(THREE.DynamicDrawUsage),
  );
  markerGeometry.setAttribute(
    "colour",
    new THREE.Float32BufferAttribute(new Float32Array([...rgb(ink().selected), ...rgb(ink().partner)]), 3),
  );
  const markerMaterial = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { uPixelRatio: { value: renderer.getPixelRatio() } },
    vertexShader: `
      attribute vec3 colour;
      uniform float uPixelRatio;
      varying vec3 vColour;
      void main() {
        vColour = colour;
        vec4 view = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = 26.0 * uPixelRatio;
        gl_Position = projectionMatrix * view;
      }`,
    fragmentShader: `
      varying vec3 vColour;
      void main() {
        float d = length(gl_PointCoord - vec2(0.5));
        if (d > 0.5 || d < 0.34) discard;
        float edge = smoothstep(0.5, 0.46, d) * smoothstep(0.34, 0.38, d);
        gl_FragColor = vec4(vColour, edge);
      }`,
  });
  const markers = new THREE.Points(markerGeometry, markerMaterial);
  markers.frustumCulled = false;
  markers.visible = false;
  scene.add(markers);

  const live = new Float32Array(count * 3);
  const velocity = new Float32Array(count * 3);
  const alive = new Uint8Array(count);
  let types: string[] = [];
  let selectedIndex: number | null = null;
  let partnerIndex: number | null = null;

  const baseSize = 2.0;
  const raycaster = new THREE.Raycaster();
  raycaster.params.Points = { threshold: 0.14 };

  function applyColours() {
    const colours = colourAttribute.array as Float32Array;
    const sizes = sizeAttribute.array as Float32Array;
    for (let i = 0; i < count; i += 1) {
      let colour: [number, number, number];
      let size = baseSize;
      if (i === selectedIndex) {
        colour = rgb(ink().selected);
        size = baseSize * 3.2;
      } else if (i === partnerIndex) {
        colour = rgb(ink().partner);
        size = baseSize * 3.2;
      } else {
        colour = rgbFor(types[i] ?? "UNK");
      }
      colours[i * 3] = colour[0];
      colours[i * 3 + 1] = colour[1];
      colours[i * 3 + 2] = colour[2];
      sizes[i] = size;
    }
    colourAttribute.needsUpdate = true;
    sizeAttribute.needsUpdate = true;
  }

  function writePositions() {
    const target = positionAttribute.array as Float32Array;
    for (let i = 0; i < count; i += 1) {
      if (!alive[i]) {
        // Park dead objects far behind the camera rather than at the origin, where
        // they would pile into a bright dot in the middle of the Earth.
        target[i * 3] = 0;
        target[i * 3 + 1] = -1e6;
        target[i * 3 + 2] = 0;
        continue;
      }
      const [x, y, z] = toScene(live[i * 3], live[i * 3 + 1], live[i * 3 + 2]);
      target[i * 3] = x;
      target[i * 3 + 1] = y;
      target[i * 3 + 2] = z;
    }
    positionAttribute.needsUpdate = true;
    geometry.computeBoundingSphere();
    writeMarkers();
  }

  function writeMarkers() {
    const target = markerGeometry.getAttribute("position") as THREE.BufferAttribute;
    const array = target.array as Float32Array;
    const place = (slot: number, index: number | null) => {
      if (index === null || !alive[index]) {
        // Out of sight rather than at the origin, which would park a ring in the
        // middle of the Earth whenever nothing was selected.
        array[slot * 3] = 0;
        array[slot * 3 + 1] = -1e6;
        array[slot * 3 + 2] = 0;
        return;
      }
      const [x, y, z] = toScene(live[index * 3], live[index * 3 + 1], live[index * 3 + 2]);
      array[slot * 3] = x;
      array[slot * 3 + 1] = y;
      array[slot * 3 + 2] = z;
    };
    place(0, selectedIndex);
    place(1, partnerIndex);
    target.needsUpdate = true;
    markers.visible = selectedIndex !== null || partnerIndex !== null;
  }

  return {
    canvas: renderer.domElement,

    setPositions(positions, velocities, ok) {
      live.set(positions);
      velocity.set(velocities);
      alive.set(ok);
      writePositions();
    },

    advance(seconds) {
      // Carry each point along its own velocity between worker updates. Over a
      // fraction of a second this is worth metres, and it is the difference between
      // motion that looks continuous and motion that ticks.
      for (let i = 0; i < count * 3; i += 1) live[i] += velocity[i] * seconds;
      writePositions();
    },

    setTypes(next) {
      types = next;
      applyColours();
    },

    setHighlight(selected, partner) {
      selectedIndex = selected;
      partnerIndex = partner;
      applyColours();
      writeMarkers();
    },

    pick(clientX, clientY) {
      const rect = renderer.domElement.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObject(points, false);
      for (const hit of hits) {
        const index = hit.index;
        if (index !== undefined && alive[index]) return index;
      }
      return null;
    },

    focus(index) {
      if (!alive[index]) return;
      const [x, y, z] = toScene(live[index * 3], live[index * 3 + 1], live[index * 3 + 2]);
      const target = new THREE.Vector3(x, y, z).normalize();
      const distance = camera.position.length();
      camera.position.copy(target.multiplyScalar(distance));
      controls.target.set(0, 0, 0);
      controls.update();
    },

    resize() {
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (width === 0 || height === 0) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    },

    render() {
      controls.update();
      renderer.render(scene, camera);
    },

    setGround(colour) {
      scene.background = new THREE.Color(colour);
    },

    /** Re-read the palette after the ground mode changed, and repaint every point. */
    refreshTheme() {
      scene.background = new THREE.Color(groundColour());
      (shell.material as THREE.MeshBasicMaterial).color.set(furniture().shell);
      applyColours();
    },

    dispose() {
      controls.dispose();
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      markerGeometry.dispose();
      markerMaterial.dispose();
      renderer.domElement.remove();
    },
  };
}
