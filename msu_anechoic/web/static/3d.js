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

function addEndWallSection(parent, width, height, z, y) {
    const section = new THREE.Mesh(
        new THREE.BoxGeometry(0.15, height, width),
        wallMaterial,
    );
    section.position.set(0, y, z);
    section.castShadow = true;
    section.receiveShadow = true;
    parent.add(section);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(section.geometry),
        new THREE.LineBasicMaterial({ color: 0x151515 }),
    );
    section.add(edges);
}

const backWall = new THREE.Group();
backWall.name = "back-wall";
backWall.position.x = -5;
scene.add(backWall);
addEndWallSection(backWall, 5, 3.5, 0, 1.75);

const frontWall = new THREE.Group();
frontWall.name = "front-wall";
frontWall.position.x = 5;
scene.add(frontWall);

// Four sections surround a 75 cm square opening centered at y=2.5, z=0.
addEndWallSection(frontWall, 2.125, 3.5, -1.4375, 1.75);
addEndWallSection(frontWall, 2.125, 3.5, 1.4375, 1.75);
addEndWallSection(frontWall, 0.75, 2.125, 0, 1.0625);
addEndWallSection(frontWall, 0.75, 0.625, 0, 3.1875);

const sourceAntenna = new THREE.Mesh(
    new THREE.SphereGeometry(0.125, 32, 16),
    new THREE.MeshStandardMaterial({
        color: 0x2ecc71,
        metalness: 0.15,
        roughness: 0.5,
    }),
);
sourceAntenna.name = "source-antenna";
sourceAntenna.position.set(5, 2.5, 0);
sourceAntenna.castShadow = true;
scene.add(sourceAntenna);

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

const fixedTable = new THREE.Mesh(
    new THREE.BoxGeometry(1.5, 0.5, 0.75),
    new THREE.MeshStandardMaterial({
        color: 0x777d84,
        metalness: 0.15,
        roughness: 0.8,
    }),
);
fixedTable.name = "fixed-turntable-table";
fixedTable.position.set(-3.5, 0.25, 0);
fixedTable.castShadow = true;
fixedTable.receiveShadow = true;
scene.add(fixedTable);

const fixedTableEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(fixedTable.geometry),
    new THREE.LineBasicMaterial({ color: 0x202428 }),
);
fixedTable.add(fixedTableEdges);

const liftMaterial = new THREE.MeshStandardMaterial({
    color: 0x4f5964,
    metalness: 0.4,
    roughness: 0.55,
});

function makeLiftPlate(name, y) {
    const plate = new THREE.Mesh(
        new THREE.BoxGeometry(1.5, 0.1, 0.75),
        liftMaterial,
    );
    plate.name = name;
    plate.position.set(-3.5, y, 0);
    plate.castShadow = true;
    plate.receiveShadow = true;

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(plate.geometry),
        new THREE.LineBasicMaterial({ color: 0x15191d }),
    );
    plate.add(edges);
    return plate;
}

const liftBottom = makeLiftPlate("scissor-lift-bottom", 0.55);
scene.add(liftBottom);

const heightAssembly = new THREE.Group();
heightAssembly.name = "height-assembly";
scene.add(heightAssembly);

const liftTop = makeLiftPlate("scissor-lift-top", 0.65);
heightAssembly.add(liftTop);

const housingShape = new THREE.Shape();
housingShape.moveTo(0, 0);
housingShape.lineTo(0.875, 0);
housingShape.lineTo(0.625, 0.55);
housingShape.closePath();

const turntableHousing = new THREE.Mesh(
    new THREE.ExtrudeGeometry(housingShape, {
        depth: 0.05,
        bevelEnabled: false,
    }),
    new THREE.MeshStandardMaterial({
        color: 0x59636e,
        metalness: 0.3,
        roughness: 0.65,
    }),
);
turntableHousing.name = "right-turntable-housing";
turntableHousing.position.set(-3.625, 0.7, 0.325);
turntableHousing.castShadow = true;
turntableHousing.receiveShadow = true;
heightAssembly.add(turntableHousing);

const turntableHousingEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(turntableHousing.geometry),
    new THREE.LineBasicMaterial({ color: 0x171b20 }),
);
turntableHousing.add(turntableHousingEdges);

const leftTurntableHousing = turntableHousing.clone(true);
leftTurntableHousing.name = "left-turntable-housing";
leftTurntableHousing.position.z = -0.375;
heightAssembly.add(leftTurntableHousing);

const scissorForks = new THREE.Group();
scissorForks.name = "scissor-forks";
scene.add(scissorForks);

const forkMaterial = liftMaterial;

const forkPairs = [];
for (const sideZ of [-0.3, 0.3]) {
    const risingForward = new THREE.Mesh(
        new THREE.BoxGeometry(1, 0.05, 0.05),
        forkMaterial,
    );
    const risingBackward = new THREE.Mesh(
        new THREE.BoxGeometry(1, 0.05, 0.05),
        forkMaterial,
    );
    risingForward.position.z = sideZ - 0.015;
    risingBackward.position.z = sideZ + 0.015;
    risingForward.castShadow = true;
    risingBackward.castShadow = true;
    scissorForks.add(risingForward, risingBackward);
    forkPairs.push({ risingForward, risingBackward });
}

function updateScissorForks(height) {
    const nominalForkLength = 1.2;
    const horizontalSpan = Math.sqrt(Math.max(
        0.05 ** 2,
        nominalForkLength ** 2 - height ** 2,
    ));
    const actualForkLength = Math.hypot(horizontalSpan, height);
    const angle = Math.atan2(height, horizontalSpan);

    for (const { risingForward, risingBackward } of forkPairs) {
        risingForward.position.x = -3.5;
        risingForward.position.y = 0.6 + height / 2;
        risingForward.scale.x = actualForkLength;
        risingForward.rotation.z = angle;

        risingBackward.position.x = -3.5;
        risingBackward.position.y = 0.6 + height / 2;
        risingBackward.scale.x = actualForkLength;
        risingBackward.rotation.z = -angle;
    }
}

const turntable = new THREE.Group();
turntable.name = "turntable";
turntable.position.set(-3, 1.225, 0);
heightAssembly.add(turntable);

const tiltAssembly = new THREE.Group();
tiltAssembly.name = "tilt-assembly";
turntable.add(tiltAssembly);

const panAssembly = new THREE.Group();
panAssembly.name = "pan-assembly";
panAssembly.position.y = 0.1;
tiltAssembly.add(panAssembly);

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

const tiltMaterial = new THREE.MeshStandardMaterial({
    color: 0xd46a1f,
    metalness: 0.35,
    roughness: 0.55,
});

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
    tiltMaterial,
);
tiltDisk.name = "tilt-disk";
tiltDisk.rotation.x = Math.PI / 2;
tiltDisk.position.set(0, 0.025, -0.3);
tiltDisk.castShadow = true;
tiltDisk.receiveShadow = true;
tiltAssembly.add(tiltDisk);

const tiltDiskEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(tiltDisk.geometry),
    new THREE.LineBasicMaterial({ color: 0x401c08 }),
);
tiltDisk.add(tiltDiskEdges);

const tiltHousing = new THREE.Mesh(
    new THREE.BoxGeometry(0.4, 0.2, 0.6),
    tiltMaterial,
);
tiltHousing.name = "tilt-housing";
tiltHousing.position.y = -0.075;
tiltHousing.castShadow = true;
tiltHousing.receiveShadow = true;
tiltAssembly.add(tiltHousing);

const tiltHousingEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(tiltHousing.geometry),
    new THREE.LineBasicMaterial({ color: 0x401c08 }),
);
tiltHousing.add(tiltHousingEdges);

const tiltShaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.025, 0.025, 1, 32),
    tiltMaterial,
);
tiltShaft.name = "tilt-shaft";
tiltShaft.rotation.x = Math.PI / 2;
tiltShaft.position.set(tiltDisk.position.x, tiltDisk.position.y, 0);
tiltShaft.castShadow = true;
tiltAssembly.add(tiltShaft);

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

const autBoresight = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0.2, 0.4, 0),
    2.5,
    0x00e5ff,
    0.15,
    0.08,
);
autBoresight.name = "aut-boresight";
antennaUnderTest.add(autBoresight);

const grid = new THREE.GridHelper(14, 14, 0x7f8c99, 0x4c5661);
grid.position.y = 0.005;
scene.add(grid);

const axes = new THREE.Group();
axes.name = "chamber-axes";
axes.position.y = 1.015;
axes.scale.setScalar(0.25);
axes.add(new THREE.AxesHelper(1.5));
scene.add(axes);

function makeAxisLabel(text, color, position) {
    const labelCanvas = document.createElement("canvas");
    labelCanvas.width = 512;
    labelCanvas.height = 128;
    const context = labelCanvas.getContext("2d");
    context.font = "bold 42px sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillStyle = color;
    context.fillText(text, 256, 64);

    const texture = new THREE.CanvasTexture(labelCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const label = new THREE.Sprite(new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthTest: false,
    }));
    label.position.copy(position);
    label.scale.set(1.6, 0.4, 1);
    label.renderOrder = 10;
    axes.add(label);
}

makeAxisLabel("X / FORWARD", "#ff5555", new THREE.Vector3(1.75, 0, 0));
makeAxisLabel("Y / UP", "#55dd77", new THREE.Vector3(0, 1.75, 0));
makeAxisLabel("Z / RIGHT", "#5599ff", new THREE.Vector3(0, 0, 1.75));

const panInput = document.getElementById("pan");
const tiltInput = document.getElementById("tilt");
const heightInput = document.getElementById("height");

function numericInputValue(input) {
    const value = Number.parseFloat(input.value);
    return Number.isFinite(value) ? value : 0;
}

function updateTurntablePose() {
    const pan = numericInputValue(panInput);
    const tilt = numericInputValue(tiltInput);
    const height = Math.max(0, numericInputValue(heightInput));

    panAssembly.rotation.y = -THREE.MathUtils.degToRad(pan);
    tiltAssembly.rotation.z = THREE.MathUtils.degToRad(tilt);
    heightAssembly.position.y = height;
    updateScissorForks(height);
}

panInput.addEventListener("input", updateTurntablePose);
tiltInput.addEventListener("input", updateTurntablePose);
heightInput.addEventListener("input", updateTurntablePose);
updateTurntablePose();

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
