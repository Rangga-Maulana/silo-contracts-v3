// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.28;

import {console2} from "forge-std/console2.sol";
import {Script} from "forge-std/Script.sol";

import {IERC4626} from "openzeppelin5/interfaces/IERC4626.sol";

import {AddrLib} from "silo-foundry-utils/lib/AddrLib.sol";
import {ChainsLib} from "silo-foundry-utils/lib/ChainsLib.sol";

import {ISilo} from "silo-core/contracts/interfaces/ISilo.sol";
import {ISiloIncentivesController} from "silo-core/contracts/incentives/interfaces/ISiloIncentivesController.sol";
import {ISiloVault} from "silo-vaults/contracts/interfaces/ISiloVault.sol";
import {ISiloVaultDeployer} from "silo-vaults/contracts/interfaces/ISiloVaultDeployer.sol";
import {IIncentivesClaimingLogicFactory} from "silo-vaults/contracts/interfaces/IIncentivesClaimingLogicFactory.sol";
import {SiloVaultsContracts, SiloVaultsDeployments} from "silo-vaults/common/SiloVaultsContracts.sol";

import {CommonDeploy} from "./common/CommonDeploy.sol";

/*
FOUNDRY_PROFILE=vaults forge script silo-vaults/deploy/DeployTestVault.s.sol:DeployTestVault \
    --ffi --rpc-url $RPC_ARBITRUM --broadcast --verify

============== DEPLOYED =================================
1 day timelock:
        vault 0x159CD30288c687353a672dBB1e482fc4c18f3e66
        incentivesController 0x52064E5165b227847bfdDC84d36A22683EB122c2
        idleVault 0x08Df2F141B12556F7c05A35F89a0FBf2b92dF89c

============== DEPLOYED =================================
1 minute vault:
  SiloVaultDeployer 0xD186343c00057488a18825f1513860Ff56e6561b
  SiloIncentivesControllerCLFactory 0x38C5CC1498Ec96E7FFC5AFd67527c91844f2269D

        vault 0x8934145E24686679d47eE5e24ebC9D5c8aDA2E7a
        incentivesController 0xB88a3e3E6169B36a50292AAf45df98Ee832a0dbA
        idleVault 0xcCE3815a22bcBa28a764DD8863658E31727430E9
========================================================
*/
contract DeployTestVault is CommonDeploy {
    function run() external {
        uint256 privateKey = uint256(vm.envBytes32("PRIVATE_KEY"));

        AddrLib.init();

        string memory network = ChainsLib.chainAlias();

        ISiloVaultDeployer deployer =
            ISiloVaultDeployer(SiloVaultsDeployments.get(SiloVaultsContracts.SILO_VAULT_DEPLOYER, network));

        // 0xD186343c00057488a18825f1513860Ff56e6561b - no timelock deployer
        deployer = ISiloVaultDeployer(0xD186343c00057488a18825f1513860Ff56e6561b);

        IIncentivesClaimingLogicFactory[] memory trustedFactories = new IIncentivesClaimingLogicFactory[](1);
        trustedFactories[0] = IIncentivesClaimingLogicFactory(
            SiloVaultsDeployments.get(SiloVaultsContracts.SILO_INCENTIVES_CONTROLLER_CL_FACTORY, network)
        );

        console2.log("chain alias", network);
        console2.log("SiloVaultDeployer", address(deployer));
        console2.log("SiloIncentivesControllerCLFactory", address(trustedFactories[0]));

        ISilo[] memory silosWithIncentives = new ISilo[](0);

        address initialOwner = AddrLib.getAddress("TEST_MULTISIG");
        address asset = AddrLib.getAddress("TEST_TOKEN_18");

        vm.startBroadcast(privateKey);

        (ISiloVault vault, ISiloIncentivesController incentivesController, IERC4626 idleVault) = deployer.createSiloVault(
            ISiloVaultDeployer.CreateSiloVaultParams({
                initialOwner: initialOwner,
                initialTimelock: 1 minutes,
                asset: asset,
                incentivesControllerOwner: initialOwner,
                name: "Test for TEST_TOKEN_18",
                symbol: "TV-TT18",
                trustedFactories: trustedFactories,
                silosWithIncentives: silosWithIncentives
            })
        );

        vm.stopBroadcast();

        console2.log("\n============== DEPLOYED =================================");
        console2.log("\tvault", address(vault));
        console2.log("\tincentivesController", address(incentivesController));
        console2.log("\tidleVault", address(idleVault));
        console2.log("========================================================");
    }
}
