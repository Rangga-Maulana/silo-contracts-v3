// SPDX-License-Identifier: BUSL-1.1
pragma solidity 0.8.28;

import {console2} from "forge-std/console2.sol";

import {IVaultIncentivesModule} from "silo-vaults/contracts/interfaces/IVaultIncentivesModule.sol";
import {ISiloVault} from "silo-vaults/contracts/interfaces/ISiloVault.sol";
import {ISiloVaultDeployer} from "silo-vaults/contracts/interfaces/ISiloVaultDeployer.sol";
import {IIncentivesClaimingLogicFactory} from "silo-vaults/contracts/interfaces/IIncentivesClaimingLogicFactory.sol";
import {ISilo} from "silo-core/contracts/interfaces/ISilo.sol";
import {CommonDeploy} from "./common/CommonDeploy.sol";
import {IERC20Metadata} from "openzeppelin5/token/ERC20/extensions/IERC20Metadata.sol";
import {ChainsLib} from "silo-foundry-utils/lib/ChainsLib.sol";
import {AddrLib} from "silo-foundry-utils/lib/AddrLib.sol";

import {SiloVaultsContracts, SiloVaultsDeployments} from "silo-vaults/common/SiloVaultsContracts.sol";

/*
FOUNDRY_PROFILE=vaults ASSET=USDC \
    forge script silo-vaults/deploy/SiloVaultsSetup.s.sol:SiloVaultsSetup \
    --ffi --rpc-url $RPC_ARBITRUM --broadcast

This script sets up the vault for QA.

*/
contract SiloVaultsSetup is CommonDeploy {
    function run() public {
        ISiloVaultDeployer vaultDeployer = ISiloVaultDeployer(
            SiloVaultsDeployments.get(SiloVaultsContracts.SILO_VAULT_DEPLOYER, ChainsLib.chainAlias())
        );

        AddrLib.init();
        address asset = AddrLib.getAddress(vm.envString("ASSET"));
        string memory assetSymbol = IERC20Metadata(asset).symbol();
        string memory vaultName = string.concat("Silo Vault for ", assetSymbol);
        string memory vaultSymbol = string.concat("SV-", assetSymbol);

        IIncentivesClaimingLogicFactory[] memory trustedFactories = new IIncentivesClaimingLogicFactory[](1);
        ISilo[] memory silosWithIncentives = new ISilo[](0);

        uint256 supplyCap = 10 * 10 ** IERC20Metadata(asset).decimals();

        uint256 privateKey = uint256(vm.envBytes32("PRIVATE_KEY"));
        address deployer = vm.addr(privateKey);

        vm.startBroadcast(privateKey);

        (ISiloVault vault,,) = vaultDeployer.createSiloVault(
            ISiloVaultDeployer.CreateSiloVaultParams({
                initialOwner: deployer,
                initialTimelock: 1 days,
                asset: asset,
                incentivesControllerOwner: deployer,
                name: vaultName,
                symbol: vaultSymbol,
                trustedFactories: trustedFactories,
                silosWithIncentives: silosWithIncentives
            })
        );

        vault.submitCap(vault, supplyCap);

        console2.log("Vault deployed at", address(vault));

        vm.stopBroadcast();
    }
}
