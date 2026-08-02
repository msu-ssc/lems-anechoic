import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";

RectAreaLightUniformsLib.init();

const canvas = document.getElementById("chamber-canvas");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x20242a);
scene.background = new THREE.Color(0x000000);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(7, 5.5, 13);

const controls = new OrbitControls(camera, canvas);
controls.target.set(-3, 1.325, 0);
controls.enableDamping = true;
controls.autoRotate = false;
controls.autoRotateSpeed = 5;

const fillLight = new THREE.HemisphereLight(0xffffff, 0x303840, 0);
scene.add(fillLight);

const sunlight = new THREE.DirectionalLight(0xffffff, 0);
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
    color: 0x183149,
    roughness: 1,
    metalness: 0,
    side: THREE.FrontSide,
    transparent: false,
    opacity: 1,
    depthWrite: true,
});

function addWallSection(parent, width, height, x, y) {
    const section = new THREE.Mesh(
        new THREE.PlaneGeometry(width, height),
        wallMaterial,
    );
    section.position.set(x, y, 0);
    // The right wall faces inward toward -Z; the left wall faces +Z.
    if (parent === wall) section.rotation.y = Math.PI;
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
        new THREE.PlaneGeometry(width, height),
        wallMaterial,
    );
    section.position.set(0, y, z);
    // The back wall faces +X; the front wall faces -X.
    section.rotation.y = parent === backWall ? Math.PI / 2 : -Math.PI / 2;
    section.castShadow = true;
    section.receiveShadow = true;
    parent.add(section);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(section.geometry),
        new THREE.LineBasicMaterial({ color: 0x151515 }),
    );
    section.add(edges);
}

function addExteriorFramePart(parent, geometry, x, y, z) {
    const part = new THREE.Mesh(geometry, wallMaterial);
    part.position.set(x, y, z);
    part.castShadow = true;
    part.receiveShadow = true;
    parent.add(part);
}

const doorExteriorFrame = new THREE.Group();
doorExteriorFrame.name = "door-exterior-frame";
wall.add(doorExteriorFrame);

// A 50 cm-wide, 15 cm-thick frame wholly outside the side-wall plane.
addExteriorFramePart(doorExteriorFrame, new THREE.BoxGeometry(0.5, 2.5, 0.15), -3.25, 1.25, 0.076);
addExteriorFramePart(doorExteriorFrame, new THREE.BoxGeometry(0.5, 2.5, 0.15), -1.75, 1.25, 0.076);
addExteriorFramePart(doorExteriorFrame, new THREE.BoxGeometry(1, 0.5, 0.15), -2.5, 2.25, 0.076);

const backWall = new THREE.Group();
backWall.name = "back-wall";
backWall.position.x = -5;
scene.add(backWall);
addEndWallSection(backWall, 5, 3.5, 0, 1.75);

const backLightMaterial = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0xffffff,
    emissiveIntensity: 800,
    roughness: 0.35,
});
const backAreaLights = [];

for (const z of [-1.5, 1.5]) {
    const fixture = new THREE.Mesh(
        new THREE.BoxGeometry(0.02, 0.3, 0.1),
        backLightMaterial,
    );
    fixture.name = "back-wall-light-fixture";
    fixture.position.set(-4.915, 2.5, z);
    scene.add(fixture);

    const areaLight = new THREE.RectAreaLight(0xffffff, 800, 0.1, 0.3);
    areaLight.name = "back-wall-area-light";
    areaLight.position.set(-4.9, 2.5, z);
    areaLight.lookAt(0, 2.5, z);
    scene.add(areaLight);
    backAreaLights.push(areaLight);
}

const floodStand = new THREE.Group();
floodStand.name = "flood-light-stand";
floodStand.position.set(-2, 0, 1.5);
scene.add(floodStand);

const floodStandMaterial = new THREE.MeshStandardMaterial({
    color: 0xe4b51b,
    metalness: 0.25,
    roughness: 0.55,
});
const floodFrameMaterial = new THREE.MeshStandardMaterial({
    color: 0x151719,
    metalness: 0.35,
    roughness: 0.65,
});
const floodPanelMaterial = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0xffffff,
    emissiveIntensity: 800,
    roughness: 0.25,
});

const floodPole = new THREE.Mesh(
    new THREE.CylinderGeometry(0.025, 0.025, 1.4, 20),
    floodStandMaterial,
);
floodPole.position.y = 0.7;
floodPole.castShadow = true;
floodStand.add(floodPole);

function makeRodBetween(start, end, radius, material) {
    const direction = end.clone().sub(start);
    const rod = new THREE.Mesh(
        new THREE.CylinderGeometry(radius, radius, direction.length(), 12),
        material,
    );
    rod.position.copy(start).add(end).multiplyScalar(0.5);
    rod.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        direction.normalize(),
    );
    rod.castShadow = true;
    return rod;
}

for (const foot of [
    new THREE.Vector3(0.45, 0.02, 0.3),
    new THREE.Vector3(-0.45, 0.02, 0.3),
    new THREE.Vector3(0, 0.02, -0.5),
]) {
    floodStand.add(makeRodBetween(
        new THREE.Vector3(0, 0.28, 0),
        foot,
        0.018,
        floodStandMaterial,
    ));
}

const floodCrossbar = new THREE.Mesh(
    new THREE.BoxGeometry(0.8, 0.04, 0.04),
    floodStandMaterial,
);
floodCrossbar.position.y = 1.38;
floodCrossbar.castShadow = true;
floodStand.add(floodCrossbar);

const floodHeadAssembly = new THREE.Group();
floodHeadAssembly.name = "fixed-flood-heads";
floodHeadAssembly.position.set(-2, 1.5, 1.5);
const defaultAutTarget = new THREE.Vector3(-2.9, 1.925, 0);
floodHeadAssembly.lookAt(defaultAutTarget);
scene.add(floodHeadAssembly);

const floodAreaLights = [];
for (const x of [-0.22, 0.22]) {
    const head = new THREE.Group();
    head.position.x = x;
    floodHeadAssembly.add(head);

    const frame = new THREE.Mesh(
        new THREE.BoxGeometry(0.32, 0.22, 0.07),
        floodFrameMaterial,
    );
    frame.castShadow = true;
    head.add(frame);

    const panel = new THREE.Mesh(
        new THREE.BoxGeometry(0.26, 0.16, 0.012),
        floodPanelMaterial,
    );
    panel.position.z = 0.041;
    head.add(panel);

    const areaLight = new THREE.RectAreaLight(0xffffff, 800, 0.26, 0.16);
    areaLight.position.z = 0.05;
    areaLight.rotation.y = Math.PI;
    head.add(areaLight);
    floodAreaLights.push(areaLight);
}

const frontWall = new THREE.Group();
frontWall.name = "front-wall";
frontWall.position.x = 5;
scene.add(frontWall);

// Four sections surround a 75 cm square opening centered at y=2.5, z=0.
addEndWallSection(frontWall, 2.125, 3.5, -1.4375, 1.75);
addEndWallSection(frontWall, 2.125, 3.5, 1.4375, 1.75);
addEndWallSection(frontWall, 0.75, 2.125, 0, 1.0625);
addEndWallSection(frontWall, 0.75, 0.625, 0, 3.1875);

const sourceExteriorFrame = new THREE.Group();
sourceExteriorFrame.name = "source-exterior-frame";
frontWall.add(sourceExteriorFrame);

// A 50 cm-wide, 15 cm-thick frame wholly outside the front-wall plane.
addExteriorFramePart(
    sourceExteriorFrame,
    new THREE.BoxGeometry(0.15, 1.75, 0.5),
    0.076,
    2.5,
    -0.625,
);
addExteriorFramePart(
    sourceExteriorFrame,
    new THREE.BoxGeometry(0.15, 1.75, 0.5),
    0.076,
    2.5,
    0.625,
);
addExteriorFramePart(
    sourceExteriorFrame,
    new THREE.BoxGeometry(0.15, 0.5, 0.75),
    0.076,
    1.875,
    0,
);
addExteriorFramePart(
    sourceExteriorFrame,
    new THREE.BoxGeometry(0.15, 0.5, 0.75),
    0.076,
    3.125,
    0,
);

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
    new THREE.PlaneGeometry(10, 5),
    new THREE.MeshStandardMaterial({
        color: 0x353b42,
        roughness: 1,
        side: THREE.FrontSide,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
    }),
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = 0;
floor.receiveShadow = true;
scene.add(floor);

const roof = new THREE.Mesh(
    new THREE.PlaneGeometry(10, 5),
    wallMaterial,
);
roof.name = "chamber-roof";
roof.rotation.x = Math.PI / 2;
roof.position.y = 3.5;
roof.castShadow = true;
roof.receiveShadow = true;
scene.add(roof);

const fixedTable = new THREE.Mesh(
    new THREE.BoxGeometry(1.5, 0.5, 0.75),
    new THREE.MeshStandardMaterial({
        color: 0x777d84,
        metalness: 0.15,
        roughness: 0.8,
    }),
);
fixedTable.name = "fixed-turntable-table";
fixedTable.position.set(-3.9, 0.25, 0);
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
    plate.position.set(-3.9, y, 0);
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
housingShape.lineTo(0.6, 0);
housingShape.lineTo(0.8, 0.55);
housingShape.lineTo(0.7, 0.55);
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
turntableHousing.position.set(-3.75, 0.7, 0.325);
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
        risingForward.position.x = -3.9;
        risingForward.position.y = 0.6 + height / 2;
        risingForward.scale.x = actualForkLength;
        risingForward.rotation.z = angle;

        risingBackward.position.x = -3.9;
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
tiltAssembly.position.y = 0.025;
turntable.add(tiltAssembly);

const panAssembly = new THREE.Group();
panAssembly.name = "pan-assembly";
panAssembly.position.y = 0.075;
tiltAssembly.add(panAssembly);

const turningSurface = new THREE.Mesh(
    new THREE.CylinderGeometry(0.4, 0.4, 0.05, 64),
    new THREE.MeshStandardMaterial({
        color: 0x6f42c1,
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
tiltDisk.position.set(0, 0, -0.3);
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
tiltHousing.position.y = -0.1;
tiltHousing.castShadow = true;
tiltHousing.receiveShadow = true;
tiltAssembly.add(tiltHousing);

const tiltHousingEdges = new THREE.LineSegments(
    new THREE.EdgesGeometry(tiltHousing.geometry),
    new THREE.LineBasicMaterial({ color: 0x401c08 }),
);
tiltHousing.add(tiltHousingEdges);

const tiltShaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.025, 0.025, 0.8, 32),
    tiltMaterial,
);
tiltShaft.name = "tilt-shaft";
tiltShaft.rotation.x = Math.PI / 2;
tiltShaft.position.set(tiltDisk.position.x, tiltDisk.position.y, 0);
tiltShaft.castShadow = true;
tiltAssembly.add(tiltShaft);

const autMount = new THREE.Group();
autMount.name = "aut-mount";
autMount.position.y = 0.125;
panAssembly.add(autMount);

const autMountMaterial = new THREE.MeshStandardMaterial({
    color: 0x6f42c1,
    roughness: 0.65,
});

function addAutMountPart(geometry, x, y, z) {
    const part = new THREE.Mesh(geometry, autMountMaterial);
    part.position.set(x, y, z);
    part.castShadow = true;
    part.receiveShadow = true;
    autMount.add(part);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: 0x24143f }),
    );
    part.add(edges);
}

// Two-centimeter top and bottom plates preserve the original 20 cm height.
addAutMountPart(new THREE.BoxGeometry(0.3, 0.02, 0.6), 0, -0.09, 0);
addAutMountPart(new THREE.BoxGeometry(0.3, 0.02, 0.6), 0, 0.09, 0);

// Two-centimeter square posts fill the 16 cm gap between the plates.
for (const x of [-0.14, 0.14]) {
    for (const z of [-0.29, 0.29]) {
        addAutMountPart(new THREE.BoxGeometry(0.02, 0.16, 0.02), x, 0, z);
    }
}

const antennaUnderTest = new THREE.Group();
antennaUnderTest.name = "antenna-under-test";
antennaUnderTest.position.y = 0.225;
panAssembly.add(antennaUnderTest);

const autMaterial = new THREE.MeshStandardMaterial({
    color: 0xe0b323,
    metalness: 0.2,
    roughness: 0.55,
});

function addAutSection(geometry, x, y, z, parent = antennaUnderTest) {
    const section = new THREE.Mesh(geometry, autMaterial);
    section.position.set(x, y, z);
    section.castShadow = true;
    section.receiveShadow = true;
    parent.add(section);

    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(section.geometry),
        new THREE.LineBasicMaterial({ color: 0x4d3900 }),
    );
    section.add(edges);
    return section;
}

// A 2.5 cm square stem rising 20 cm from the mounting box.
const autStem = addAutSection(new THREE.BoxGeometry(1, 1, 1), 0, 0.1, 0);
autStem.scale.set(0.025, 0.2, 0.025);

// A 20 cm arm extending forward (+X) from the top of the stem.
const autArm = addAutSection(new THREE.BoxGeometry(1, 1, 1), 0.1, 0.175, 0);
autArm.scale.set(0.2, 0.025, 0.025);

// Only the antenna plate rotates. Its pivot is the forward end of the fixed arm.
const autAntennaPivot = new THREE.Group();
autAntennaPivot.name = "aut-antenna-pivot";
autAntennaPivot.position.set(0.2, 0.175, 0);
antennaUnderTest.add(autAntennaPivot);

// A 10 cm square, 2 cm thick patch antenna.
const autAntenna = addAutSection(
    new THREE.BoxGeometry(1, 1, 1),
    0.01,
    0,
    0,
    autAntennaPivot,
);
autAntenna.scale.set(0.02, 0.1, 0.1);

const autBoresightOrigin = new THREE.Vector3(0.02, 0, 0);

const autBoresight = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    autBoresightOrigin,
    2.5,
    0xe0b323,
    0.15,
    0.08,
);
autBoresight.name = "aut-boresight";
autAntennaPivot.add(autBoresight);

const autCoordinateFrame = new THREE.Object3D();
autCoordinateFrame.name = "aut-coordinate-frame";
autCoordinateFrame.position.copy(autBoresightOrigin);
autAntennaPivot.add(autCoordinateFrame);

function updateAutMounting(height, depth, horizontalPosition, pitch, roll, yaw) {
    const tubeThickness = 0.025;
    const antennaThickness = 0.02;

    antennaUnderTest.position.z = horizontalPosition;

    autStem.scale.set(tubeThickness, height, tubeThickness);
    autStem.position.set(0, height / 2, 0);

    autArm.scale.set(depth, tubeThickness, tubeThickness);
    autArm.position.set(depth / 2, height - tubeThickness / 2, 0);

    autAntennaPivot.position.set(depth, height - tubeThickness / 2, 0);
    autAntenna.scale.set(antennaThickness, 0.1, 0.1);
    autAntenna.position.set(antennaThickness / 2, 0, 0);

    autBoresightOrigin.set(antennaThickness, 0, 0);
    autBoresight.position.copy(autBoresightOrigin);
    autCoordinateFrame.position.copy(autBoresightOrigin);

    // +X is forward, +Y is up, and +Z is right. Rotate only the patch
    // antenna about its connection to the fixed periscope arm.
    autAntennaPivot.rotation.set(
        THREE.MathUtils.degToRad(roll),
        -THREE.MathUtils.degToRad(yaw),
        THREE.MathUtils.degToRad(pitch),
        "YZX",
    );
}

const tiltAssemblyBoresight = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0, 0, 0),
    1.25,
    0xd46a1f,
    0.12,
    0.06,
);
tiltAssemblyBoresight.name = "tilt-assembly-boresight";
tiltAssembly.add(tiltAssemblyBoresight);

const panAssemblyBoresight = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0, 0, 0),
    1.25,
    0x6f42c1,
    0.12,
    0.06,
);
panAssemblyBoresight.name = "pan-assembly-boresight";
panAssembly.add(panAssemblyBoresight);

const autToSourceVector = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0, 0, 0),
    1,
    0x4cff70,
    0.15,
    0.08,
);
autToSourceVector.name = "aut-to-source-vector";
scene.add(autToSourceVector);

const autWorldPosition = new THREE.Vector3();
const sourceWorldPosition = new THREE.Vector3();
const autToSourceDirection = new THREE.Vector3();
const sourceInAutCoordinates = new THREE.Vector3();

function updateSourceCoordinateReadout() {
    sourceInAutCoordinates.copy(sourceWorldPosition);
    autCoordinateFrame.worldToLocal(sourceInAutCoordinates);

    const { x, y, z } = sourceInAutCoordinates;
    const range = sourceInAutCoordinates.length();
    const azimuth = THREE.MathUtils.radToDeg(Math.atan2(z, x));
    const elevation = THREE.MathUtils.radToDeg(
        Math.atan2(y, Math.hypot(x, z)),
    );

    sourceAutXOutput.textContent = `${x.toFixed(3)} m`;
    sourceAutYOutput.textContent = `${y.toFixed(3)} m`;
    sourceAutZOutput.textContent = `${z.toFixed(3)} m`;
    sourceAutAzimuthOutput.textContent = `${azimuth.toFixed(2)}°`;
    sourceAutElevationOutput.textContent = `${elevation.toFixed(2)}°`;
    sourceAutRangeOutput.textContent = `${range.toFixed(3)} m`;
}

function updateAutToSourceVector() {
    autCoordinateFrame.updateWorldMatrix(true, false);
    sourceAntenna.updateWorldMatrix(true, false);

    autCoordinateFrame.getWorldPosition(autWorldPosition);
    sourceAntenna.getWorldPosition(sourceWorldPosition);

    autToSourceDirection.subVectors(sourceWorldPosition, autWorldPosition);
    const length = autToSourceDirection.length();
    if (length <= 1e-9) return;

    autToSourceVector.position.copy(autWorldPosition);
    autToSourceVector.setDirection(autToSourceDirection.normalize());
    autToSourceVector.setLength(length, 0.15, 0.08);
    updateSourceCoordinateReadout();
}

const MAX_TRAIL_POINTS = 2000;
const TRAIL_MINIMUM_MOVEMENT_METERS = 0.001;
const trailPositions = new Float32Array(MAX_TRAIL_POINTS * 3);
const trailPositionAttribute = new THREE.BufferAttribute(trailPositions, 3);
trailPositionAttribute.setUsage(THREE.DynamicDrawUsage);

const trailGeometry = new THREE.BufferGeometry();
trailGeometry.setAttribute("position", trailPositionAttribute);
trailGeometry.setDrawRange(0, 0);

const trailLine = new THREE.Line(
    trailGeometry,
    new THREE.LineBasicMaterial({ color: 0xff3bd5 }),
);
trailLine.name = "boresight-trail-line";
trailLine.frustumCulled = false;
scene.add(trailLine);

let trailPointCount = 0;
let trailSampleElapsed = 0;

function clearBoresightTrail() {
    trailPointCount = 0;
    trailGeometry.setDrawRange(0, 0);
    trailPositionAttribute.needsUpdate = true;
}

function sampleBoresightTrailPoint(radius) {
    autAntennaPivot.updateWorldMatrix(true, false);
    const point = autAntennaPivot.localToWorld(
        autBoresightOrigin.clone().add(new THREE.Vector3(radius, 0, 0)),
    );

    if (trailPointCount > 0) {
        const lastOffset = (trailPointCount - 1) * 3;
        const distanceFromLast = point.distanceTo(new THREE.Vector3(
            trailPositions[lastOffset],
            trailPositions[lastOffset + 1],
            trailPositions[lastOffset + 2],
        ));
        if (distanceFromLast < TRAIL_MINIMUM_MOVEMENT_METERS) return;
    }

    if (trailPointCount === MAX_TRAIL_POINTS) {
        trailPositions.copyWithin(0, 3);
        trailPointCount -= 1;
    }

    const offset = trailPointCount * 3;
    trailPositions[offset] = point.x;
    trailPositions[offset + 1] = point.y;
    trailPositions[offset + 2] = point.z;
    trailPointCount += 1;
    trailGeometry.setDrawRange(0, trailPointCount);
    trailPositionAttribute.needsUpdate = true;
}

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
const autHeightInput = document.getElementById("aut-height");
const autDepthInput = document.getElementById("aut-depth");
const autHorizontalPositionInput = document.getElementById("aut-horizontal-position");
const autPitchInput = document.getElementById("aut-pitch");
const autRollInput = document.getElementById("aut-roll");
const autYawInput = document.getElementById("aut-yaw");
const panSlider = document.getElementById("pan-slider");
const tiltSlider = document.getElementById("tilt-slider");
const heightSlider = document.getElementById("height-slider");
const autHeightSlider = document.getElementById("aut-height-slider");
const autDepthSlider = document.getElementById("aut-depth-slider");
const autHorizontalPositionSlider = document.getElementById("aut-horizontal-position-slider");
const autPitchSlider = document.getElementById("aut-pitch-slider");
const autRollSlider = document.getElementById("aut-roll-slider");
const autYawSlider = document.getElementById("aut-yaw-slider");
const wallOpacitySlider = document.getElementById("wall-opacity");
const wallOpacityOutput = document.getElementById("wall-opacity-output");
const rotationToggle = document.getElementById("rotation-toggle");
const rotationSpeedSlider = document.getElementById("rotation-speed");
const rotationSpeedOutput = document.getElementById("rotation-speed-output");
const motionAnimationToggle = document.getElementById("motion-animation-toggle");
const screenRadiusSlider = document.getElementById("screen-radius");
const screenRadiusOutput = document.getElementById("screen-radius-output");
const trailEnabledInput = document.getElementById("trail-enabled");
const trailClearButton = document.getElementById("trail-clear");
const trailSampleIntervalSlider = document.getElementById("trail-sample-interval");
const trailSampleIntervalOutput = document.getElementById("trail-sample-interval-output");
const backLightIntensitySlider = document.getElementById("back-light-intensity");
const backLightIntensityOutput = document.getElementById("back-light-intensity-output");
const fillLightIntensitySlider = document.getElementById("fill-light-intensity");
const fillLightIntensityOutput = document.getElementById("fill-light-intensity-output");
const directionalLightIntensitySlider = document.getElementById("directional-light-intensity");
const directionalLightIntensityOutput = document.getElementById("directional-light-intensity-output");
const floodLightIntensitySlider = document.getElementById("flood-light-intensity");
const floodLightIntensityOutput = document.getElementById("flood-light-intensity-output");
const settingsToggle = document.getElementById("settings-toggle");
const settingsPanel = document.getElementById("settings-panel");
const sourceAutXOutput = document.getElementById("source-aut-x");
const sourceAutYOutput = document.getElementById("source-aut-y");
const sourceAutZOutput = document.getElementById("source-aut-z");
const sourceAutAzimuthOutput = document.getElementById("source-aut-azimuth");
const sourceAutElevationOutput = document.getElementById("source-aut-elevation");
const sourceAutRangeOutput = document.getElementById("source-aut-range");

settingsToggle.addEventListener("click", () => {
    settingsPanel.hidden = !settingsPanel.hidden;
    settingsToggle.setAttribute("aria-expanded", String(!settingsPanel.hidden));
});

function numericInputValue(input) {
    const value = Number.parseFloat(input.value);
    return Number.isFinite(value) ? value : 0;
}

function updateTurntablePose() {
    const pan = THREE.MathUtils.clamp(numericInputValue(panInput), -180, 180);
    const tilt = THREE.MathUtils.clamp(numericInputValue(tiltInput), -90, 45);
    const height = THREE.MathUtils.clamp(numericInputValue(heightInput), 0, 1);
    const autHeight = THREE.MathUtils.clamp(numericInputValue(autHeightInput), 0.05, 1);
    const autDepth = THREE.MathUtils.clamp(numericInputValue(autDepthInput), 0.05, 1);
    const autHorizontalPosition = THREE.MathUtils.clamp(
        numericInputValue(autHorizontalPositionInput),
        -0.3,
        0.3,
    );
    const autPitch = THREE.MathUtils.clamp(numericInputValue(autPitchInput), -180, 180);
    const autRoll = THREE.MathUtils.clamp(numericInputValue(autRollInput), -180, 180);
    const autYaw = THREE.MathUtils.clamp(numericInputValue(autYawInput), -180, 180);

    panAssembly.rotation.y = -THREE.MathUtils.degToRad(pan);
    tiltAssembly.rotation.z = THREE.MathUtils.degToRad(tilt);
    heightAssembly.position.y = height;
    updateAutMounting(
        autHeight,
        autDepth,
        autHorizontalPosition,
        autPitch,
        autRoll,
        autYaw,
    );
    updateScissorForks(height);
    updateAutToSourceVector();
}

function bindSlider(numberInput, slider) {
    numberInput.addEventListener("input", () => {
        slider.value = numberInput.value;
        updateTurntablePose();
    });
    slider.addEventListener("input", () => {
        numberInput.value = slider.value;
        updateTurntablePose();
    });
}

bindSlider(panInput, panSlider);
bindSlider(tiltInput, tiltSlider);
bindSlider(heightInput, heightSlider);
bindSlider(autHeightInput, autHeightSlider);
bindSlider(autDepthInput, autDepthSlider);
bindSlider(autHorizontalPositionInput, autHorizontalPositionSlider);
bindSlider(autPitchInput, autPitchSlider);
bindSlider(autRollInput, autRollSlider);
bindSlider(autYawInput, autYawSlider);

const parameterAnimations = [
    {
        input: panInput,
        slider: panSlider,
        speed: document.getElementById("pan-animation-speed"),
        speedOutput: document.getElementById("pan-animation-speed-output"),
        minimumInput: document.getElementById("pan-animation-min"),
        maximumInput: document.getElementById("pan-animation-max"),
        hardMinimum: -180,
        hardMaximum: 180,
        speedUnit: "deg/s",
        speedPrecision: 0,
        direction: 1,
    },
    {
        input: tiltInput,
        slider: tiltSlider,
        speed: document.getElementById("tilt-animation-speed"),
        speedOutput: document.getElementById("tilt-animation-speed-output"),
        minimumInput: document.getElementById("tilt-animation-min"),
        maximumInput: document.getElementById("tilt-animation-max"),
        hardMinimum: -90,
        hardMaximum: 45,
        speedUnit: "deg/s",
        speedPrecision: 1,
        direction: 1,
    },
    {
        input: heightInput,
        slider: heightSlider,
        speed: document.getElementById("height-animation-speed"),
        speedOutput: document.getElementById("height-animation-speed-output"),
        minimumInput: document.getElementById("height-animation-min"),
        maximumInput: document.getElementById("height-animation-max"),
        hardMinimum: 0,
        hardMaximum: 1,
        speedUnit: "m/s",
        speedPrecision: 2,
        direction: 1,
    },
];

for (const animation of parameterAnimations) {
    animation.speed.addEventListener("input", () => {
        const speed = Number.parseFloat(animation.speed.value);
        animation.speedOutput.value = (
            `${speed.toFixed(animation.speedPrecision)} ${animation.speedUnit}`
        );
        animation.speedOutput.textContent = animation.speedOutput.value;
    });
}

let motionAnimationActive = false;
motionAnimationToggle.addEventListener("click", () => {
    motionAnimationActive = !motionAnimationActive;
    motionAnimationToggle.textContent = motionAnimationActive ? "Stop" : "Start";
});

screenRadiusSlider.addEventListener("input", () => {
    const radius = Number.parseFloat(screenRadiusSlider.value);
    screenRadiusOutput.value = `${radius.toFixed(2)} m`;
    screenRadiusOutput.textContent = screenRadiusOutput.value;
});

trailSampleIntervalSlider.addEventListener("input", () => {
    const milliseconds = Number.parseInt(trailSampleIntervalSlider.value, 10);
    trailSampleIntervalOutput.value = `${milliseconds} ms`;
    trailSampleIntervalOutput.textContent = trailSampleIntervalOutput.value;
    trailSampleElapsed = 0;
});

trailEnabledInput.addEventListener("change", () => {
    trailSampleElapsed = 0;
    if (trailEnabledInput.checked) {
        sampleBoresightTrailPoint(Number.parseFloat(screenRadiusSlider.value));
    }
});

trailClearButton.addEventListener("click", clearBoresightTrail);

backLightIntensitySlider.addEventListener("input", () => {
    const intensity = Number.parseFloat(backLightIntensitySlider.value);
    backLightMaterial.emissiveIntensity = intensity;
    for (const light of backAreaLights) light.intensity = intensity;
    backLightIntensityOutput.value = intensity.toFixed(1);
    backLightIntensityOutput.textContent = backLightIntensityOutput.value;
});

floodLightIntensitySlider.addEventListener("input", () => {
    const intensity = Number.parseFloat(floodLightIntensitySlider.value);
    floodPanelMaterial.emissiveIntensity = intensity;
    for (const light of floodAreaLights) light.intensity = intensity;
    floodLightIntensityOutput.value = intensity.toFixed(1);
    floodLightIntensityOutput.textContent = floodLightIntensityOutput.value;
});

fillLightIntensitySlider.addEventListener("input", () => {
    fillLight.intensity = Number.parseFloat(fillLightIntensitySlider.value);
    fillLightIntensityOutput.value = fillLight.intensity.toFixed(1);
    fillLightIntensityOutput.textContent = fillLightIntensityOutput.value;
});

directionalLightIntensitySlider.addEventListener("input", () => {
    sunlight.intensity = Number.parseFloat(directionalLightIntensitySlider.value);
    directionalLightIntensityOutput.value = sunlight.intensity.toFixed(1);
    directionalLightIntensityOutput.textContent = directionalLightIntensityOutput.value;
});

function animationBounds(animation) {
    const minimum = THREE.MathUtils.clamp(
        numericInputValue(animation.minimumInput),
        animation.hardMinimum,
        animation.hardMaximum,
    );
    const maximum = THREE.MathUtils.clamp(
        numericInputValue(animation.maximumInput),
        animation.hardMinimum,
        animation.hardMaximum,
    );
    return maximum > minimum ? { minimum, maximum } : null;
}

function setAnimatedValue(animation, value) {
    const precision = animation.hardMaximum <= 1 ? 3 : 2;
    animation.input.value = value.toFixed(precision);
    animation.slider.value = String(value);
}

function advanceBouncingAnimation(animation, deltaSeconds) {
    const speed = Number.parseFloat(animation.speed.value);
    const bounds = animationBounds(animation);
    if (speed <= 0 || !bounds) return false;

    const current = THREE.MathUtils.clamp(
        numericInputValue(animation.input),
        bounds.minimum,
        bounds.maximum,
    );
    let value = current + animation.direction * speed * deltaSeconds;
    if (value >= bounds.maximum) {
        value = bounds.maximum;
        animation.direction = -1;
    } else if (value <= bounds.minimum) {
        value = bounds.minimum;
        animation.direction = 1;
    }
    setAnimatedValue(animation, value);
    return true;
}

let serpentinePhase = "pan";
let serpentineTiltTarget = null;
let serpentineTiltDirection = 1;

function nextSerpentineTiltTarget(current, minimum, maximum) {
    const step = Math.max(
        0.1,
        Math.abs(numericInputValue(document.getElementById("tilt-animation-step"))),
    );
    let candidate = current + serpentineTiltDirection * step;

    if (candidate > maximum) {
        if (current < maximum - 1e-9) return maximum;
        serpentineTiltDirection = -1;
        return current;
    } else if (candidate < minimum) {
        if (current > minimum + 1e-9) return minimum;
        serpentineTiltDirection = 1;
        return current;
    }
    return THREE.MathUtils.clamp(candidate, minimum, maximum);
}

function updateSerpentinePanTilt(deltaSeconds) {
    const [panAnimation, tiltAnimation] = parameterAnimations;
    const panBounds = animationBounds(panAnimation);
    const tiltBounds = animationBounds(tiltAnimation);
    if (!panBounds || !tiltBounds) return false;

    if (serpentinePhase === "tilt") {
        const tiltSpeed = Number.parseFloat(tiltAnimation.speed.value);
        const current = THREE.MathUtils.clamp(
            numericInputValue(tiltAnimation.input),
            tiltBounds.minimum,
            tiltBounds.maximum,
        );
        const target = THREE.MathUtils.clamp(
            serpentineTiltTarget,
            tiltBounds.minimum,
            tiltBounds.maximum,
        );
        const remaining = target - current;
        const movement = tiltSpeed * deltaSeconds;
        if (Math.abs(remaining) <= movement) {
            setAnimatedValue(tiltAnimation, target);
            serpentinePhase = "pan";
            serpentineTiltTarget = null;
        } else {
            setAnimatedValue(
                tiltAnimation,
                current + Math.sign(remaining) * movement,
            );
        }
        return true;
    }

    const panSpeed = Number.parseFloat(panAnimation.speed.value);
    const current = THREE.MathUtils.clamp(
        numericInputValue(panAnimation.input),
        panBounds.minimum,
        panBounds.maximum,
    );
    let value = current + panAnimation.direction * panSpeed * deltaSeconds;
    let reachedEnd = false;
    if (value >= panBounds.maximum) {
        value = panBounds.maximum;
        panAnimation.direction = -1;
        reachedEnd = true;
    } else if (value <= panBounds.minimum) {
        value = panBounds.minimum;
        panAnimation.direction = 1;
        reachedEnd = true;
    }
    setAnimatedValue(panAnimation, value);

    if (reachedEnd) {
        const currentTilt = THREE.MathUtils.clamp(
            numericInputValue(tiltAnimation.input),
            tiltBounds.minimum,
            tiltBounds.maximum,
        );
        serpentineTiltTarget = nextSerpentineTiltTarget(
            currentTilt,
            tiltBounds.minimum,
            tiltBounds.maximum,
        );
        if (Math.abs(serpentineTiltTarget - currentTilt) > 1e-9) {
            serpentinePhase = "tilt";
        }
    }
    return true;
}

function updateParameterAnimations(deltaSeconds) {
    if (!motionAnimationActive) return;

    const [panAnimation, tiltAnimation, heightAnimation] = parameterAnimations;
    const panSpeed = Number.parseFloat(panAnimation.speed.value);
    const tiltSpeed = Number.parseFloat(tiltAnimation.speed.value);

    let changed;
    if (panSpeed > 0 && tiltSpeed > 0) {
        changed = updateSerpentinePanTilt(deltaSeconds);
    } else {
        serpentinePhase = "pan";
        serpentineTiltTarget = null;
        const panChanged = advanceBouncingAnimation(panAnimation, deltaSeconds);
        const tiltChanged = advanceBouncingAnimation(tiltAnimation, deltaSeconds);
        changed = panChanged || tiltChanged;
    }
    changed = advanceBouncingAnimation(heightAnimation, deltaSeconds) || changed;
    if (changed) updateTurntablePose();
}

function updateBoresightTrail(deltaSeconds) {
    if (!trailEnabledInput.checked) {
        trailSampleElapsed = 0;
        return;
    }

    trailSampleElapsed += deltaSeconds;
    const intervalSeconds = Number.parseFloat(trailSampleIntervalSlider.value) / 1000;
    if (trailSampleElapsed < intervalSeconds) return;
    trailSampleElapsed %= intervalSeconds;
    sampleBoresightTrailPoint(Number.parseFloat(screenRadiusSlider.value));
}

wallOpacitySlider.addEventListener("input", () => {
    const opacity = Number.parseFloat(wallOpacitySlider.value);
    const isOpaque = opacity >= 0.999;
    wallMaterial.opacity = opacity;
    wallMaterial.transparent = !isOpaque;
    wallMaterial.depthWrite = isOpaque;
    wallMaterial.needsUpdate = true;
    wallOpacityOutput.value = `${Math.round(wallMaterial.opacity * 100)}%`;
    wallOpacityOutput.textContent = wallOpacityOutput.value;
});

rotationToggle.addEventListener("click", () => {
    controls.autoRotate = !controls.autoRotate;
    rotationToggle.textContent = controls.autoRotate ? "Stop" : "Start";
});

rotationSpeedSlider.addEventListener("input", () => {
    controls.autoRotateSpeed = Number.parseFloat(rotationSpeedSlider.value);
    rotationSpeedOutput.value = `${controls.autoRotateSpeed.toFixed(1)}x`;
    rotationSpeedOutput.textContent = rotationSpeedOutput.value;
});
updateTurntablePose();

function resize() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

const clock = new THREE.Clock();

function render() {
    const deltaSeconds = clock.getDelta();
    resize();
    updateParameterAnimations(deltaSeconds);
    updateBoresightTrail(deltaSeconds);
    controls.update(deltaSeconds);
    renderer.render(scene, camera);
    requestAnimationFrame(render);
}

render();
