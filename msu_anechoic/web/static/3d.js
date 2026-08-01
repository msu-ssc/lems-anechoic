import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const canvas = document.getElementById("chamber-canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x20242a);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(7, 5.5, 13);

const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 1.75, 0);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x303840, 2.4));

const sunlight = new THREE.DirectionalLight(0xffffff, 2.5);
sunlight.position.set(2, 8, 8);
sunlight.castShadow = true;
scene.add(sunlight);

const wall = new THREE.Group();
wall.name = "right-wall";
wall.position.z = 2.5;
scene.add(wall);

const leftWall = new THREE.Group();
leftWall.name = "left-wall";
leftWall.position.z = -2.5;
scene.add(leftWall);

const wallMaterial = new THREE.MeshStandardMaterial({
    color: 0xaaaaaa,
    roughness: 0.85,
    transparent: true,
    opacity: 0.3,
    depthWrite: false,
});

function addWallSection(parent, width, height, x, y) {
    const section = new THREE.Mesh(
        new THREE.BoxGeometry(width, height, 0.15),
        wallMaterial,
    );
    section.position.set(x, y, 0);
    section.castShadow = true;
    section.receiveShadow = true;
    parent.add(section);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(section.geometry),
        new THREE.LineBasicMaterial({ color: 0x151515 }),
    );
    section.add(edges);
}

// Right wall: 10 m wide, 3.5 m high. Door: 1 m wide, 2 m high,
// 2 m from the left edge.
addWallSection(wall, 2, 3.5, -4, 1.75);
addWallSection(wall, 7, 3.5, 1.5, 1.75);
addWallSection(wall, 1, 1.5, -2.5, 2.75);

// Left wall: solid, parallel to and 5 m from the right wall.
addWallSection(leftWall, 10, 3.5, 0, 1.75);

function addEndWall(x) {
    const endWall = new THREE.Mesh(
        new THREE.BoxGeometry(0.15, 3.5, 5),
        wallMaterial,
    );
    endWall.position.set(x, 1.75, 0);
    endWall.castShadow = true;
    endWall.receiveShadow = true;
    scene.add(endWall);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(endWall.geometry),
        new THREE.LineBasicMaterial({ color: 0x151515 }),
    );
    endWall.add(edges);
}

addEndWall(-5);
addEndWall(5);

const floor = new THREE.Mesh(
    new THREE.BoxGeometry(10, 0.15, 5),
    new THREE.MeshStandardMaterial({
        color: 0x353b42,
        roughness: 1,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
    }),
);
floor.position.y = -0.075;
floor.receiveShadow = true;
scene.add(floor);

const turntable = new THREE.Group();
turntable.name = "turntable";
turntable.position.set(-3, 1.225, 0);
scene.add(turntable);

const panAssembly = new THREE.Group();
panAssembly.name = "pan-assembly";
turntable.add(panAssembly);

const turningSurface = new THREE.Mesh(
    new THREE.CylinderGeometry(0.4, 0.4, 0.05, 64),
    new THREE.MeshStandardMaterial({
        color: 0x365f91,
        metalness: 0.35,
        roughness: 0.55,
    }),
);
turningSurface.name = "turning-surface";
turningSurface.castShadow = true;
turningSurface.receiveShadow = true;
panAssembly.add(turningSurface);

const turningSurfaceEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(turningSurface.geometry),
    new THREE.LineBasicMaterial({ color: 0x101820 }),
);
turningSurface.add(turningSurfaceEdges);

const tiltDisk = new THREE.Mesh(
    new THREE.CylinderGeometry(
        0.4,
        0.4,
        0.05,
        64,
        1,
        false,
        -Math.PI / 2,
        Math.PI,
    ),
    new THREE.MeshStandardMaterial({
        color: 0xd46a1f,
        metalness: 0.35,
        roughness: 0.55,
    }),
);
tiltDisk.name = "tilt-disk";
tiltDisk.rotation.x = Math.PI / 2;
tiltDisk.position.set(0, 0.025, -0.3);
tiltDisk.castShadow = true;
tiltDisk.receiveShadow = true;
turntable.add(tiltDisk);

const tiltDiskEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(tiltDisk.geometry),
    new THREE.LineBasicMaterial({ color: 0x401c08 }),
);
tiltDisk.add(tiltDiskEdges);

const autMount = new THREE.Mesh(
    new THREE.BoxGeometry(0.3, 0.2, 0.6),
    new THREE.MeshStandardMaterial({
        color: 0x6f42c1,
        roughness: 0.65,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
    }),
);
autMount.name = "aut-mount";
autMount.position.y = 0.125;
autMount.castShadow = true;
autMount.receiveShadow = true;
panAssembly.add(autMount);

const autMountEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(autMount.geometry),
    new THREE.LineBasicMaterial({ color: 0x24143f }),
);
autMount.add(autMountEdges);

const antennaUnderTest = new THREE.Group();
antennaUnderTest.name = "antenna-under-test";
panAssembly.add(antennaUnderTest);

const autMaterial = new THREE.MeshStandardMaterial({
    color: 0xe0b323,
    metalness: 0.2,
    roughness: 0.55,
});

function addAutSection(geometry, x, y, z) {
    const section = new THREE.Mesh(geometry, autMaterial);
    section.position.set(x, y, z);
    section.castShadow = true;
    section.receiveShadow = true;
    antennaUnderTest.add(section);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(section.geometry),
        new THREE.LineBasicMaterial({ color: 0x4d3900 }),
    );
    section.add(edges);
}

// A 5 cm square stem rising 20 cm from the mounting box.
addAutSection(new THREE.BoxGeometry(0.05, 0.2, 0.05), 0, 0.325, 0);

// A 20 cm arm extending forward (+X) from the top of the stem.
addAutSection(new THREE.BoxGeometry(0.2, 0.05, 0.05), 0.1, 0.4, 0);

const grid = new THREE.GridHelper(14, 14, 0x7f8c99, 0x4c5661);
grid.position.y = 0.005;
scene.add(grid);

function resize() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

function render() {
    resize();
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(render);
}

render();
